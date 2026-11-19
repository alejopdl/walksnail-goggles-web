/// DVR Gallery screen — lists recordings from the goggles SD card.
///
/// Features:
///   - Video thumbnails generated from the goggles' HTTP file server
///   - Multi-select for batch downloads
///   - Cancel downloads in progress
///   - Sort by name, duration, or file size
///   - Downloaded clips are saved to the phone's Gallery/Photos (album "WS WiFi Stream")
import 'dart:async';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:provider/provider.dart';
import 'package:path_provider/path_provider.dart';
import 'package:gal/gal.dart';
import '../providers/goggles_state.dart';
import '../services/ws_api.dart';

enum SortBy { name, duration, size }

/// Temp file for a clip being downloaded; refuses names that would leave [dir].
String clipTempPath(String dir, String filename) =>
    '$dir/${checkClipName(filename)}';

class GalleryScreen extends StatefulWidget {
  const GalleryScreen({super.key});

  @override
  State<GalleryScreen> createState() => _GalleryScreenState();
}

class _GalleryScreenState extends State<GalleryScreen> {
  List<Map<String, dynamic>> _records = [];
  bool _loading = true;
  String? _error;
  SortBy _sortBy = SortBy.name;
  bool _sortAscending = false;

  // Multi-select state.
  final Set<String> _selected = {};
  bool _selectMode = false;

  // Download tracking: filename -> progress (0.0 to 1.0).
  final Map<String, double> _downloading = {};
  // Active download subscriptions for cancellation.
  final Map<String, StreamSubscription> _downloadSubs = {};
  // Completers resolved when a download fully finishes (done/error/cancel),
  // so batch downloads can await true completion, one clip at a time.
  final Map<String, Completer<void>> _downloadDone = {};

  GogglesState? _goggles;

  @override
  void initState() {
    super.initState();
    // Pause telemetry polling while the gallery is open so the heavy DVR
    // query / downloads don't compete with telemetry on the goggles.
    _goggles = context.read<GogglesState>();
    _goggles?.pausePolling();
    _loadRecords();
  }

  @override
  void dispose() {
    // Cancel all active downloads on exit.
    for (final sub in _downloadSubs.values) {
      sub.cancel();
    }
    // Release anything awaiting a download so batch loops don't hang.
    for (final done in _downloadDone.values) {
      if (!done.isCompleted) done.complete();
    }
    _downloadDone.clear();
    _goggles?.resumePolling();
    super.dispose();
  }

  // --------------- Data Loading ---------------

  Future<void> _loadRecords() async {
    setState(() {
      _loading = true;
      _error = null;
    });

    try {
      final api = context.read<GogglesState>().api;
      final data = await api.listRecords();
      final rows = (data['rows'] as List<dynamic>?) ?? [];
      final records = rows.cast<Map<String, dynamic>>();

      // (File sizes and thumbnails will be fetched lazily in the list builder)
      setState(() {
        _records = records;
        _loading = false;
      });
    } catch (e) {
      setState(() {
        _error = e.toString();
        _loading = false;
      });
    }
  }

  Future<void> _fetchFileSize(String url, Map<String, dynamic> record) async {
    try {
      final response =
          await http.head(Uri.parse(url)).timeout(const Duration(seconds: 5));
      final contentLength = response.headers['content-length'];
      if (contentLength != null && mounted) {
        setState(() {
          record['_fileSize'] = int.tryParse(contentLength) ?? 0;
        });
      }
    } catch (_) {}
  }

  // --------------- Downloads ---------------

  /// Stream the download into a temp file first; once complete it is copied into
  /// the phone's Gallery/Photos (see [_downloadFile]). Using the Gallery (rather
  /// than a raw Downloads path) means the clip is actually visible in the user's
  /// photo app and works with Android scoped storage.
  Future<String> _getDownloadDir() async {
    final dir = await getTemporaryDirectory();
    return dir.path;
  }

  /// Downloads one clip. The returned future completes only when the transfer
  /// has fully finished (saved, failed or cancelled) — batch downloads await it
  /// so clips transfer strictly one at a time: the goggles' tiny one-shot HTTP
  /// server chokes on parallel file reads.
  Future<void> _downloadFile(String filename) async {
    if (_downloading.containsKey(filename)) return; // Already downloading.

    final api = context.read<GogglesState>().api;
    final url = api.recordUrl(filename);
    final done = Completer<void>();

    setState(() => _downloading[filename] = 0.0);

    try {
      final downloadDir = await _getDownloadDir();
      final filePath = clipTempPath(downloadDir, filename);
      final file = File(filePath);

      final request = http.Request('GET', Uri.parse(url));
      final streamedResponse =
          await request.send().timeout(const Duration(minutes: 10));

      final totalBytes = streamedResponse.contentLength ?? 0;
      int receivedBytes = 0;
      final sink = file.openWrite();

      final sub = streamedResponse.stream.listen(
        (chunk) {
          sink.add(chunk);
          receivedBytes += chunk.length;
          if (totalBytes > 0 && mounted) {
            setState(() {
              _downloading[filename] = receivedBytes / totalBytes;
            });
          }
        },
        onDone: () async {
          await sink.close();

          // Save the finished clip into the phone's Gallery/Photos (album
          // "WS WiFi Stream") — the place users actually look for videos. `gal`
          // handles Photos (iOS) and MediaStore (Android) plus permissions.
          String message;
          Color color = Colors.green.shade800;
          try {
            if (!await Gal.hasAccess(toAlbum: true)) {
              await Gal.requestAccess(toAlbum: true);
            }
            await Gal.putVideo(filePath, album: 'WS WiFi Stream');
            message = 'Saved to Gallery — album "WS WiFi Stream"';
          } catch (e) {
            message = 'Downloaded, but could not save to Gallery: $e';
            color = Colors.orange.shade800;
          } finally {
            if (await file.exists()) await file.delete();
          }

          if (mounted) {
            setState(() {
              _downloading.remove(filename);
              _downloadSubs.remove(filename);
            });
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(
                content: Text(message),
                backgroundColor: color,
              ),
            );
          }
          if (!done.isCompleted) done.complete();
        },
        onError: (e) async {
          await sink.close();
          // Clean up partial file.
          if (await file.exists()) await file.delete();
          if (mounted) {
            setState(() {
              _downloading.remove(filename);
              _downloadSubs.remove(filename);
            });
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(
                content: Text('Download failed: $e'),
                backgroundColor: Colors.red.shade800,
              ),
            );
          }
          if (!done.isCompleted) done.complete();
        },
        cancelOnError: true,
      );

      _downloadSubs[filename] = sub;
      // Cancellation fires neither onDone nor onError — _cancelDownload
      // completes the completer via this map so awaiting callers don't hang.
      _downloadDone[filename] = done;
      await done.future;
      _downloadDone.remove(filename);
    } catch (e) {
      if (mounted) {
        setState(() {
          _downloading.remove(filename);
          _downloadSubs.remove(filename);
        });
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Download failed: $e'),
            backgroundColor: Colors.red.shade800,
          ),
        );
      }
      if (!done.isCompleted) done.complete();
    }
  }

  void _cancelDownload(String filename) {
    _downloadSubs[filename]?.cancel();
    _downloadSubs.remove(filename);
    final done = _downloadDone.remove(filename);
    if (done != null && !done.isCompleted) done.complete();
    setState(() => _downloading.remove(filename));
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text('Cancelled $filename'),
        backgroundColor: Colors.orange.shade800,
      ),
    );
  }

  void _downloadSelected() {
    // Strictly sequential: each _downloadFile future completes only when its
    // transfer has fully finished, so clips never download in parallel (the
    // goggles' one-shot HTTP server can't serve concurrent file reads).
    final names = _selected.toList();
    () async {
      for (final filename in names) {
        if (!mounted) break;
        await _downloadFile(filename);
      }
    }();
    setState(() {
      _selected.clear();
      _selectMode = false;
    });
  }

  // --------------- Sorting ---------------

  void _applySorting() {
    _records.sort((a, b) {
      int result;
      switch (_sortBy) {
        case SortBy.name:
          final nameA = a['szFileName']?.toString() ?? '';
          final nameB = b['szFileName']?.toString() ?? '';
          result = nameA.compareTo(nameB);
          break;
        case SortBy.duration:
          final durA = a['duration'] as int? ?? 0;
          final durB = b['duration'] as int? ?? 0;
          result = durA.compareTo(durB);
          break;
        case SortBy.size:
          final sizeA = a['_fileSize'] as int? ?? 0;
          final sizeB = b['_fileSize'] as int? ?? 0;
          result = sizeA.compareTo(sizeB);
          break;
      }
      return _sortAscending ? result : -result;
    });
  }

  PopupMenuEntry<SortBy> _sortMenuItem(
      SortBy value, IconData icon, String label) {
    final isActive = _sortBy == value;
    return PopupMenuItem<SortBy>(
      value: value,
      child: Row(
        children: [
          Icon(icon,
              color: isActive ? Colors.cyanAccent : Colors.white54, size: 18),
          const SizedBox(width: 10),
          Text(
            label,
            style: TextStyle(
              color: isActive ? Colors.cyanAccent : Colors.white,
              fontWeight: isActive ? FontWeight.bold : FontWeight.normal,
            ),
          ),
          if (isActive) ...[
            const Spacer(),
            Icon(
              _sortAscending ? Icons.arrow_upward : Icons.arrow_downward,
              color: Colors.cyanAccent,
              size: 16,
            ),
          ],
        ],
      ),
    );
  }

  // --------------- Formatting ---------------

  String _formatDuration(int seconds) {
    final m = seconds ~/ 60;
    final s = seconds % 60;
    return '${m.toString().padLeft(2, '0')}:${s.toString().padLeft(2, '0')}';
  }

  String _formatFileSize(int bytes) {
    if (bytes <= 0) return '';
    if (bytes < 1024 * 1024) return '${(bytes / 1024).toStringAsFixed(0)} KB';
    if (bytes < 1024 * 1024 * 1024) {
      return '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB';
    }
    return '${(bytes / (1024 * 1024 * 1024)).toStringAsFixed(2)} GB';
  }

  /// Extract the clip number from filenames like "AvatarG0001.mp4" -> "0001".
  String _extractNumber(String filename) {
    final match = RegExp(r'(\d+)').firstMatch(filename);
    return match?.group(1) ?? '?';
  }

  // --------------- Build ---------------

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF0A0E17),
      appBar: AppBar(
        backgroundColor: const Color(0xFF0A0E17),
        leading: _selectMode
            ? IconButton(
                icon: const Icon(Icons.close, color: Colors.white),
                onPressed: () => setState(() {
                  _selectMode = false;
                  _selected.clear();
                }),
              )
            : null,
        title: Text(
          _selectMode
              ? '${_selected.length} selected'
              : 'DVR Gallery (${_records.length})',
          style: const TextStyle(
            color: Colors.white,
            fontWeight: FontWeight.w600,
          ),
        ),
        iconTheme: const IconThemeData(color: Colors.white),
        actions: [
          if (_selectMode) ...[
            // Select All.
            IconButton(
              icon: Icon(
                _selected.length == _records.length
                    ? Icons.deselect
                    : Icons.select_all,
                color: Colors.cyanAccent,
              ),
              onPressed: () {
                setState(() {
                  if (_selected.length == _records.length) {
                    _selected.clear();
                  } else {
                    _selected.clear();
                    for (final r in _records) {
                      _selected.add(r['szFileName']?.toString() ?? '');
                    }
                  }
                });
              },
              tooltip: 'Select All',
            ),
            // Download selected.
            IconButton(
              icon: const Icon(Icons.download, color: Colors.cyanAccent),
              onPressed: _selected.isEmpty ? null : _downloadSelected,
              tooltip: 'Download Selected',
            ),
          ] else ...[
            // Multi-select mode toggle.
            IconButton(
              icon: const Icon(Icons.checklist, color: Colors.white54),
              onPressed: () => setState(() => _selectMode = true),
              tooltip: 'Select Files',
            ),
            // Sort.
            PopupMenuButton<SortBy>(
              icon: const Icon(Icons.sort, color: Colors.cyanAccent),
              tooltip: 'Sort by',
              color: const Color(0xFF1A1E2E),
              onSelected: (sortBy) {
                setState(() {
                  if (_sortBy == sortBy) {
                    _sortAscending = !_sortAscending;
                  } else {
                    _sortBy = sortBy;
                    _sortAscending = false;
                  }
                  _applySorting();
                });
              },
              itemBuilder: (_) => [
                _sortMenuItem(SortBy.name, Icons.sort_by_alpha, 'Name / Date'),
                _sortMenuItem(SortBy.duration, Icons.timer, 'Duration'),
                _sortMenuItem(SortBy.size, Icons.storage, 'File Size'),
              ],
            ),
            // Refresh.
            IconButton(
              icon: const Icon(Icons.refresh, color: Colors.cyanAccent),
              onPressed: _loadRecords,
              tooltip: 'Refresh',
            ),
          ],
        ],
      ),
      body: _buildBody(),
    );
  }

  Widget _buildBody() {
    if (_loading) {
      return const Center(
        child: CircularProgressIndicator(color: Colors.cyanAccent),
      );
    }

    if (_error != null) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.error_outline, color: Colors.redAccent, size: 48),
            const SizedBox(height: 12),
            Text(
              'Could not load recordings',
              style: TextStyle(
                  color: Colors.white.withOpacity(0.7), fontSize: 16),
            ),
            const SizedBox(height: 8),
            Text(
              _error!,
              style: TextStyle(
                  color: Colors.white.withOpacity(0.4), fontSize: 12),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 16),
            ElevatedButton.icon(
              onPressed: _loadRecords,
              icon: const Icon(Icons.refresh),
              label: const Text('Retry'),
              style: ElevatedButton.styleFrom(
                backgroundColor: Colors.cyanAccent.withOpacity(0.15),
                foregroundColor: Colors.cyanAccent,
              ),
            ),
          ],
        ),
      );
    }

    if (_records.isEmpty) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.videocam_off,
                color: Colors.white.withOpacity(0.2), size: 64),
            const SizedBox(height: 12),
            Text(
              'No recordings found',
              style: TextStyle(
                  color: Colors.white.withOpacity(0.5), fontSize: 16),
            ),
          ],
        ),
      );
    }

    return ListView.separated(
      padding: const EdgeInsets.all(12),
      itemCount: _records.length,
      separatorBuilder: (_, __) => const SizedBox(height: 8),
      itemBuilder: (context, index) {
        final record = _records[index];
        final filename = record['szFileName']?.toString() ?? 'Unknown';
        final duration = record['duration'] as int? ?? 0;
        final fileSize = record['_fileSize'] as int? ?? 0;
        final downloadProgress = _downloading[filename];
        final isDownloading = downloadProgress != null;
        final isSelected = _selected.contains(filename);

        // Lazily fetch data if missing
        if (fileSize == 0 && mounted) {
          final api = context.read<GogglesState>().api;
          _fetchFileSize(api.recordUrl(filename), record);
        }

        return GestureDetector(
          onLongPress: () {
            if (!_selectMode) {
              setState(() {
                _selectMode = true;
                _selected.add(filename);
              });
            }
          },
          onTap: _selectMode
              ? () {
                  setState(() {
                    if (isSelected) {
                      _selected.remove(filename);
                      if (_selected.isEmpty) _selectMode = false;
                    } else {
                      _selected.add(filename);
                    }
                  });
                }
              : null,
          child: Container(
            decoration: BoxDecoration(
              color: isSelected
                  ? Colors.cyanAccent.withOpacity(0.1)
                  : Colors.white.withOpacity(0.05),
              borderRadius: BorderRadius.circular(12),
              border: Border.all(
                color: isSelected
                    ? Colors.cyanAccent.withOpacity(0.4)
                    : Colors.white.withOpacity(0.08),
              ),
            ),
            child: Column(
              children: [
                Row(
                  children: [
                    // Checkbox or Thumbnail.
                    if (_selectMode)
                      Padding(
                        padding: const EdgeInsets.only(left: 8),
                        child: Checkbox(
                          value: isSelected,
                          onChanged: (_) {
                            setState(() {
                              if (isSelected) {
                                _selected.remove(filename);
                                if (_selected.isEmpty) _selectMode = false;
                              } else {
                                _selected.add(filename);
                              }
                            });
                          },
                          activeColor: Colors.cyanAccent,
                          checkColor: Colors.black,
                        ),
                      ),
                    // Thumbnail placeholder with file number.
                    Padding(
                      padding: const EdgeInsets.all(10),
                      child: ClipRRect(
                        borderRadius: BorderRadius.circular(8),
                        child: Container(
                          width: 72,
                          height: 48,
                          color: Colors.cyanAccent.withOpacity(0.08),
                          child: Center(
                            child: Column(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                const Icon(Icons.videocam,
                                    color: Colors.cyanAccent, size: 18),
                                Text(
                                  '#${_extractNumber(filename)}',
                                  style: TextStyle(
                                    color: Colors.cyanAccent.withOpacity(0.7),
                                    fontSize: 10,
                                    fontWeight: FontWeight.w600,
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ),
                      ),
                    ),
                    // File info.
                    Expanded(
                      child: Padding(
                        padding: const EdgeInsets.symmetric(vertical: 10),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              filename,
                              style: const TextStyle(
                                color: Colors.white,
                                fontWeight: FontWeight.w500,
                                fontSize: 14,
                              ),
                            ),
                            const SizedBox(height: 3),
                            Text(
                              [
                                _formatDuration(duration),
                                if (fileSize > 0) _formatFileSize(fileSize),
                              ].join('  •  '),
                              style: TextStyle(
                                color: Colors.white.withOpacity(0.4),
                                fontSize: 12,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                    // Download / Cancel button.
                    if (!_selectMode)
                      Padding(
                        padding: const EdgeInsets.only(right: 8),
                        child: isDownloading
                            ? GestureDetector(
                                onTap: () => _cancelDownload(filename),
                                child: Stack(
                                  alignment: Alignment.center,
                                  children: [
                                    SizedBox(
                                      width: 36,
                                      height: 36,
                                      child: CircularProgressIndicator(
                                        value: downloadProgress,
                                        strokeWidth: 2.5,
                                        color: Colors.cyanAccent,
                                        backgroundColor: Colors.white12,
                                      ),
                                    ),
                                    const Icon(Icons.close,
                                        color: Colors.white54, size: 16),
                                  ],
                                ),
                              )
                            : IconButton(
                                icon: const Icon(Icons.download,
                                    color: Colors.cyanAccent, size: 22),
                                onPressed: () => _downloadFile(filename),
                              ),
                      ),
                  ],
                ),
                // Download progress bar.
                if (isDownloading)
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 12)
                        .copyWith(bottom: 8),
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(4),
                      child: LinearProgressIndicator(
                        value: downloadProgress,
                        minHeight: 3,
                        color: Colors.cyanAccent,
                        backgroundColor: Colors.white12,
                      ),
                    ),
                  ),
              ],
            ),
          ),
        );
      },
    );
  }
}
