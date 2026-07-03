# WS WiFi Stream — Guía de Instalación y Uso

> **Una sola descarga. Doble clic. Listo.**

---

## ¿Qué es esto?

Una aplicación de escritorio gratuita y no oficial que te permite ver el **video en vivo** de tus gafas Walksnail Avatar HD, ver la **telemetría** (voltaje, temperatura, bitrate) y gestionar tus **grabaciones DVR**, todo desde el navegador de tu computadora.

> ⚠️ **No oficial.** No tiene afiliación con Caddx ni Walksnail.  
> ✅ Probado en: **Goggles X + Avatar Mini, firmware 39.44.15**

---

## Requisitos

| | Mínimo |
|---|---|
| **Sistema** | macOS 12+ o Windows 10/11 (64-bit) |
| **Gafas** | Walksnail Avatar HD Goggles X |
| **Conexión** | WiFi de las gafas (ver abajo) |
| **Navegador** | Chrome, Firefox, Safari, Edge (cualquier moderno) |

---

## Instalación

### macOS

1. Descargá `WS-WiFi-Stream-mac.zip` de la página de [Releases](https://github.com/alejopdl/walksnail-goggles-web/releases)
2. Descomprimí el ZIP → aparece `WS-WiFi-Stream.app`
3. **Primera vez:** click derecho → **Abrir** → **Abrir** (solo la primera vez — macOS advierte sobre apps sin firma de Apple)
4. A partir de la segunda vez, doble clic directo

> **¿Por qué el aviso de macOS?**  
> La app no tiene firma de Apple (cuesta $99/año). Es normal para software open-source gratuito. El código fuente está público en GitHub para que cualquiera lo verifique.

### Windows

1. Descargá `WS-WiFi-Stream-win.zip` de la página de [Releases](https://github.com/alejopdl/walksnail-goggles-web/releases)
2. Descomprimí el ZIP en una carpeta (ej. `C:\WS-WiFi-Stream\`)
3. Abrí la carpeta y doble clic en **`WS-WiFi-Stream.exe`**
4. **Primera vez:** si Windows Defender advierte → click en **"Más información"** → **"Ejecutar de todas formas"**

> **¿Por qué el aviso de Windows?**  
> Mismo motivo — la app no tiene firma de Microsoft. El aviso desaparece en futuros lanzamientos una vez que Windows la reconoce.

---

## Cómo usarlo

### Paso 1 — Conectar la PC al WiFi de las gafas

Las gafas crean su propia red WiFi cuando están encendidas.

| | Valor |
|---|---|
| **Nombre de red (SSID)** | `Walksnail_XXXXXX` (varía por dispositivo) |
| **Contraseña** | `12345678` |

1. Encendé las gafas (con o sin dron, el WiFi siempre está activo)
2. En tu PC: conectate al WiFi `Walksnail_XXXXXX`
3. ⚠️ Tu PC **no tendrá internet** mientras estés conectado a las gafas — es normal

### Paso 2 — Abrir la aplicación

- **macOS:** Doble clic en `WS-WiFi-Stream.app`
- **Windows:** Doble clic en `WS-WiFi-Stream.exe`

Aparece una ventana de terminal con esto:

```
  ╔══════════════════════════════════════════╗
  ║   🚁  WS WiFi Stream            ║
  ║   http://localhost:8080                  ║
  ║                                          ║
  ║   The app opened in your browser.        ║
  ║   Keep this window open while using it.  ║
  ║   Press Ctrl+C here to quit.             ║
  ╚══════════════════════════════════════════╝
```

El navegador se abre **automáticamente** con la interfaz.

> **¿El navegador no se abrió solo?**  
> Abrí manualmente: `http://localhost:8080`

### Paso 3 — Usar la interfaz

---

## La interfaz

```
┌─────────────────────────────────────────────────────┐
│ 🚁 WS WiFi Stream │ AvatarX_079060 │ fw 39.44.15 │ ● LIVE │
├─────────────────────────────────────┬───────────────┤
│                                     │  Link Status  │
│                                     │  ● Goggles    │
│         VIDEO EN VIVO               │  ● VTX/Drone  │
│         (1080p, ~23 Mbps)           ├───────────────┤
│                                     │  Telemetría   │
│  BAT 22.7V  TEMP 46°C  23Mbps MCS4 │  22.69V       │
│                                     │  80°C VTX     │
├─────────────────────────────────────┤  23.3 Mbps    │
│ Stream: TCP  ● Running  521 frames  │               │
└─────────────────────────────────────┴───────────────┘
```

### Indicadores de conexión (arriba a la derecha)

| Badge | Significa |
|---|---|
| 🟢 **LIVE** | Video en vivo funcionando |
| 🟡 **Connecting** | Conectando al stream RTSP |
| 🟣 **No VTX** | Gafas OK pero sin dron vinculado |
| 🔴 **Error** | Error de red (se auto-recupera) |
| ⚫ **Offline** | Gafas no responden (¿WiFi conectado?) |

### OSD (información sobre el video)

El OSD muestra datos en tiempo real sobre el video. Viene **activo por defecto**.

- **Arriba izquierda:** voltaje batería gafas · voltaje VTX · temperatura
- **Abajo izquierda:** indicador `● REC` cuando está grabando
- **Abajo derecha:** MCS · bitrate · espacio en SD

Para mostrarlo/ocultarlo: presioná **`O`** en el teclado.

### Atajos de teclado

| Tecla | Acción |
|---|---|
| `O` | Mostrar / ocultar OSD |
| `S` | Guardar captura de pantalla |
| `F` | Pantalla completa |
| `,` | Abrir configuración del stream |
| `R` | Reintentar stream manualmente |

### Configuración del stream (tecla `,`)

> ⚠️ **Importante:** estos ajustes afectan el video que se envía **a tu navegador** (ancho de banda / CPU), **no** la captura de las gafas. La resolución y el bitrate reales se cambian en el **menú de las gafas**.

| Ajuste | Opciones | Recomendado |
|---|---|---|
| **Transporte** | TCP · UDP | TCP (más estable) |
| **Calidad JPEG** | 20% – 95% | 80% |
| **FPS máx** | 15 · 30 · 60 | 30 |

> **TCP vs UDP:**  
> TCP = imagen limpia y estable (recomendado). UDP = más fluido en WiFi débil pero puede mostrar artefactos. En un link bueno la latencia es parecida.
>
> *(La antigua opción "Resolución" se quitó: solo achicaba la imagen en el navegador, sin mejorar la calidad.)*

---

## Cerrar la aplicación

**macOS:** Presioná `Ctrl+C` en la ventana de terminal, o cerrá la ventana de terminal.  
**Windows:** Cerrá la ventana de terminal (la `X` arriba a la derecha).

El navegador puede quedar abierto — simplemente cerrá la pestaña.

---

## Solución de problemas

### El video no aparece / dice "Connecting"

1. ¿Estás conectado al WiFi de las gafas? (No al WiFi de casa)
2. ¿El dron / air unit está encendido? Sin dron no hay video RTSP
3. Presioná `R` para reintentar manualmente
4. Probá cambiar a UDP en los settings (`,`)

### Dice "Offline" (sin conexión a las gafas)

1. Verificá que tu PC está conectada al WiFi `Walksnail_XXXXXX`
2. Abrí un navegador y fijate si llegás a `http://192.168.42.1` — si no carga, es el WiFi
3. Reiniciá las gafas

### El video se ve lento / con lag

- Bajá **Calidad JPEG** y/o **FPS máx** en Settings (`,`)
- Probá **UDP** transport (más fluido en WiFi débil, puede tener artefactos)
- Cerrá otras pestañas del navegador

### El video se congeló y dice "Live feed stuck — reboot the goggles"

Las gafas sirven **una sola** sesión de video RTSP. Al cambiar de transporte o aplicar
settings muy seguido, esa sesión puede quedar trabada. La app espera antes de reconectar
y detecta el estado trabado — si ves ese mensaje, **apagá y prendé las gafas** para recuperar.

### La galería tarda en cargar

Si las gafas tienen muchos clips en la SD (cientos), la lista tarda unos segundos.
Ya no falla por timeout, solo tené paciencia.

### El video titila "No VTX" mientras las gafas arrancan

Dale unos segundos a las gafas para terminar de bootear; la detección de link tiene
*debounce* y debería estabilizarse sola.

### macOS: "No se puede abrir porque es de un desarrollador no identificado"

→ Click derecho sobre `WS-WiFi-Stream.app` → **Abrir** → **Abrir**  
Solo necesitás hacerlo una vez.

### Windows: "Windows protegió tu PC"

→ Click en **"Más información"** → **"Ejecutar de todas formas"**  
Solo necesitás hacerlo una vez.

### El puerto 8080 está ocupado

Si la app dice que el puerto está en uso, otro programa lo está usando.  
La app busca automáticamente otro puerto disponible.

---

## Para usuarios técnicos — opciones avanzadas

Si ejecutás la app desde la terminal, podés pasar argumentos:

```bash
# macOS:
./WS-WiFi-Stream.app/Contents/MacOS/WS-WiFi-Stream --port 9999 --no-browser

# Windows:
WS-WiFi-Stream.exe --port 9999 --no-browser

# Opciones:
#   --host 192.168.42.1    IP de las gafas (default)
#   --port 8080            Puerto del servidor web
#   --no-browser           No abrir el navegador automáticamente
#   --debug                Guardar un log de sesión (requests, reconexiones, VTX)
#   --debug-verbose        Igual que --debug + cuerpos completos de request/response
```

**Modo debug:** con `--debug` la app escribe un log de la sesión (cada request a las
gafas con su timing/resultado, el ciclo de reconexión RTSP, las transiciones de VTX y
la tasa de requests). Útil para reportar problemas de conexión. Se guarda en
`~/Library/Logs/WS-WiFi-Stream/` (macOS) o `%LOCALAPPDATA%\WS-WiFi-Stream\logs\` (Windows).

Para acceder desde otro dispositivo en la misma red (ej. tablet), abrí una terminal y usá:
```bash
ws-web --port 8080    # modo Python directo, sin --bind (expone a la LAN)
```
Luego en el otro dispositivo: `http://IP-DE-TU-PC:8080`

---

## Compatibilidad verificada

| Modelo | Firmware | Estado |
|---|---|---|
| Goggles X + Avatar Mini | 39.44.15 | ✅ Probado |
| Otros modelos Avatar HD | varios | ❓ Sin confirmar |

¿Lo probaste con otro modelo? [Abrí un issue](https://github.com/alejopdl/walksnail-goggles-web/issues) con tu modelo y firmware — ayuda mucho a la comunidad.

---

## Construir desde el código fuente

Si querés compilar vos mismo:

```bash
# Clonar
git clone https://github.com/alejopdl/walksnail-goggles-web
cd walksnail-goggles-web/poc/python

# Crear entorno
python3 -m venv .venv
source .venv/bin/activate          # macOS/Linux
.venv\Scripts\activate             # Windows

# Instalar dependencias
pip install -e ".[web]"
pip install pyinstaller

# Buildear
python build.py --zip

# El resultado está en dist/
```

---

*WS WiFi Stream es software libre bajo licencia MIT.*  
*No tiene afiliación con Caddx ni Walksnail.*
