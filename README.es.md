<p align="center">
  <a href="README.md">English</a> | <a href="README.zh-Hans.md">简体中文</a> | <a href="README.ja.md">日本語</a> | <a href="README.de.md">Deutsch</a> | <a href="README.ko.md">한국어</a> | <a href="README.fr.md">Français</a> | <a href="README.pt-BR.md">Português (Brasil)</a> | <b>Español</b>
</p>

# Bean Network Tester 🫘 - simulador de malas condiciones de red (Windows) 
<p align="center">
  <b>Redes del autor:</b>
  &nbsp
  <a href="https://discord.gg/bDTu8HX"><img src="https://cdn.simpleicons.org/discord/5865F2" alt="Discord" height="26" align="absmiddle"></a>
  &nbsp
  <a href="https://facebook.com/donislawdev"><img src="https://cdn.simpleicons.org/facebook/0866FF" alt="Facebook" height="26" align="absmiddle"></a>
  &nbsp
  <a href="https://x.com/donislawdev"><picture><source media="(prefers-color-scheme: dark)" srcset="https://cdn.simpleicons.org/x/FFFFFF"><img src="https://cdn.simpleicons.org/x/000000" alt="X (Twitter)" height="26" align="absmiddle"></picture></a>
  &nbsp
  <a href="https://bsky.app/profile/donislawdev.bsky.social"><img src="https://cdn.simpleicons.org/bluesky/0285FF" alt="Bluesky" height="26" align="absmiddle"></a>
  &nbsp
 <a href="https://store.steampowered.com/developer/DonislawDev"><picture><source media="(prefers-color-scheme: dark)" srcset="https://cdn.simpleicons.org/steam/FFFFFF"><img src="https://cdn.simpleicons.org/steam/000000" alt="Steam" height="26" align="absmiddle"></picture></a>
</p>

[![CI](https://github.com/donislawdev/BeanNetworkTester/actions/workflows/ci.yml/badge.svg)](https://github.com/donislawdev/BeanNetworkTester/actions/workflows/ci.yml)
[![Latest release](https://img.shields.io/github/v/release/donislawdev/BeanNetworkTester?sort=semver)](https://github.com/donislawdev/BeanNetworkTester/releases/latest)
[![Downloads](https://img.shields.io/github/downloads/donislawdev/BeanNetworkTester/total)](https://github.com/donislawdev/BeanNetworkTester/releases)
[![License: GPLv3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/donislawdev/BeanNetworkTester/badge)](https://scorecard.dev/viewer/?uri=github.com/donislawdev/BeanNetworkTester)
[![OpenSSF Best Practices](https://www.bestpractices.dev/projects/14154/badge)](https://www.bestpractices.dev/projects/14154)
![Platform: Windows](https://img.shields.io/badge/platform-Windows-0078D6)

**Bean Network Tester** es una herramienta para testers y desarrolladores: permite comprobar cómo
se comporta una aplicación con una mala conexión. Igual que Clumsy o NetLimiter, sirve para degradar
la red a propósito: añadir ping, descartar paquetes, limitar la velocidad, cortar conexiones y más.
Funciona interceptando el tráfico con el controlador **[WinDivert](https://www.reqrypt.org/windivert.html)**
(a través de **[PyDivert](https://github.com/ffalcinelli/pydivert)**), y ofrece tanto una interfaz de
ventanas clara con tooltips como un modo de línea de comandos para CI.

⭐ **Si le ha ahorrado tiempo, deje una estrella.** Así es como se entera de que existe el próximo
tester que lo necesite.

**Qué puede hacer**

- **Añadir lag y jitter** - retardo fijo o aleatorio, más picos ocasionales.
- **Descartar, corromper o duplicar paquetes** - la pérdida puede llegar en ráfagas, como falla un
  enlace inalámbrico real.
- **Limitar la velocidad de descarga y de subida** - restringir a un número fijo de KB/s, con un
  búfer que añade retardo de cola antes de empezar a descartar.
- **Cortar conexiones** - restablecimientos TCP, un enlace caído o conexiones nuevas que nunca se
  establecen.
- **Hacer que el enlace vaya y venga** - cortes que aparecen y desaparecen.
- **Romper la ruta, no solo los paquetes** - un agujero negro de MTU y tiempos de inactividad al
  estilo NAT.
- **Bloquear puertos o IP** - un pequeño cortafuegos integrado, además del modo LAN (sin internet)
  y de solo internet (sin red local).
- **Apuntar a una sola aplicación** - por nombre de proceso, PID, IP, puerto o una sola familia de
  direcciones.
- **Perfiles predefinidos y guardados** - 56k modem, Cafe WiFi, Satellite, In-flight Wi-Fi
  y más.
- **Ejecutar escenarios** - pasos temporizados que cambian la red por sí solos.
- **Programar el límite de velocidad** - una línea de tiempo repetida de velocidades, sin escribir
  un escenario.
- **Reproducible mediante semilla** - repite exactamente la misma pérdida y el mismo jitter
  aleatorios.
- **Pasar un error a otra persona** - un informe con todos los ajustes, los contadores y la
  línea de comandos que repite la ejecución.
- **Verlo en directo** - gráfico, contadores, una tabla de conexiones con búsqueda y un registro de
  eventos.
- **Exportar a CSV** - estadísticas de la sesión e instantánea de la tabla de conexiones.
- **Modo de línea de comandos** - automatizable para CI, con códigos de salida y salida JSON.
- **Sin telemetría, totalmente sin conexión** - no envía nada por su cuenta. La herramienta Ping
  solo hace ping a la dirección que se escribe.

<p align="center">
  <img src="docs/demo.gif" alt="Bean Network Tester adding lag and packet loss to a live ping" width="820">
</p>

<p align="center">
  <a href="https://github.com/donislawdev/BeanNetworkTester"><img src="docs/star.gif" alt="Like it? Star Bean Network Tester on GitHub" width="820"></a>
</p>

**Tabla de contenidos**

- [Inicio rápido (3 pasos)](#inicio-rápido-3-pasos)
- [Idioma](#idioma)
- [Requisitos](#requisitos)
- [La ventana](#la-ventana)
- [Todas las opciones explicadas](#todas-las-opciones-explicadas)
- [Sintaxis de filtros (proceso / IP / puerto)](#sintaxis-de-filtros-proceso--ip--puerto)
- [Estadísticas (qué significan los contadores)](#estadísticas-qué-significan-los-contadores)
- [Archivo de configuración](#archivo-de-configuración)
- [Modo de línea de comandos (CLI)](#modo-de-línea-de-comandos-cli)
- [Columnas de Connections](#columnas-de-connections)
- [Exportaciones a CSV](#exportaciones-a-csv)
- [Formato del archivo de escenario](#formato-del-archivo-de-escenario)
- [Recetas de CI/CD](#recetas-de-cicd)
- [Cómo crear un .exe](#cómo-crear-un-exe)
- [Trampas habituales (leer antes de abrir un informe de error)](#trampas-habituales-leer-antes-de-abrir-un-informe-de-error)
- [Pruebas](#pruebas)
- [Estructura del proyecto](#estructura-del-proyecto)
- [Cómo funciona (en resumen)](#cómo-funciona-en-resumen)
- [Notas y limitaciones](#notas-y-limitaciones)
- [Cómo contribuir](#cómo-contribuir)
- [Apoyar el proyecto](#apoyar-el-proyecto)
- [Autor](#autor)
- [Licencia](#licencia)
- [Componentes de terceros](#componentes-de-terceros)
- [Privacidad: sin telemetría](#privacidad-sin-telemetría)
- [Una nota sobre SmartScreen y el antivirus](#una-nota-sobre-smartscreen-y-el-antivirus)

## Inicio rápido (3 pasos)

1. Descargue `BeanNetworkTester`: el **zip** funciona sin instalar nada, el **`.msi`** lo instala
   para todos los usuarios del equipo, en el `PATH` y en el menú Inicio (requiere derechos de
   administrador). O compílelo: `pyinstaller --noconfirm BeanNetworkTester.spec`.
2. Ejecute `BeanNetworkTester.exe` - el programa **solicita por sí mismo los derechos de
   administrador** (WinDivert los necesita). Desde el repositorio: `python bean_network_tester.py`.
3. Elija un perfil de la lista "Profiles" (p. ej. "3G network") y haga clic en **START**.

El **mismo archivo** ejecuta el modo de texto: `BeanNetworkTester.exe --simulate --loss 10 --duration 5`.

En la parte superior de la ventana, una barra "Active: ..." resume lo que está haciendo el programa
en ese momento (p. ej. *Active: +150 ms ping, 1% loss, download <= 384 KB/s*). Al pasar el cursor
sobre cualquier campo aparece un tooltip que explica para qué sirve.

> Nota: seleccionar un perfil solo rellena los campos - el deterioro empieza únicamente con **START**.
> Sin derechos de administrador, el controlador WinDivert no se carga.

¿Se busca una tarea concreta y no el manual completo que sigue? Las
[guías del sitio web](https://beannetworktester.donislawdev.com/es/) explican la pérdida de paquetes,
la latencia, los límites de velocidad, cómo apuntar a una sola aplicación y cómo probar sin internet,
cada una con los valores que conviene probar y el comando que lo hace. Otras dos tratan de cómo
averiguar qué programa ocupa un puerto y qué usar en lugar de `tc netem` o Network Link Conditioner.
Las guías están escritas en 22 idiomas, desde inglés y polaco hasta árabe y vietnamita.

## Idioma

Las traducciones están en archivos **`lang/<code>.json`** (incluidos: `lang/en.json`, `lang/pl.json`
y `lang/zh.json`, que es chino simplificado). Al arrancar, la aplicación **examina el directorio
`lang/`** y detecta automáticamente los idiomas disponibles. El idioma de inicio sigue la
configuración regional del sistema cuando existe una traducción que coincida, y en caso contrario
recurre al inglés. Un sistema configurado en chino tradicional también recibe inglés: el archivo
incluido es de chino simplificado, y ambos son sistemas de escritura distintos, no dos ortografías de una misma.
La lista **Language** de la ventana Settings (el engranaje de la esquina superior derecha) lo cambia
en cualquier momento: la interfaz se reconstruye en el idioma elegido y conserva los ajustes
actuales.

**Todo** en la interfaz está traducido: pestañas, etiquetas, botones, tooltips, encabezados de
columna, estadísticas, el panel de sesión, el registro de eventos, los mensajes de registro, los
cuadros de diálogo y los mensajes de error (las excepciones que se muestran al usuario). El código
usa solo **claves** (p. ej. `app.tabs.statistics`) y el texto sale del archivo de idioma. Cuando
falta una clave en el idioma elegido se usa el inglés y, como último recurso, la propia clave. (La
línea de comandos - CLI - está **siempre en inglés**, con independencia del idioma del sistema y de
la interfaz.)

**Añadir un idioma nuevo** no requiere cambios en el código: copie `lang/en.json` a, por ejemplo,
`lang/de.json`, traduzca los valores y complete el encabezado `"_meta": {"code": "de", "name": "Deutsch"}`.
El idioma aparece en la lista tras reiniciar. Un archivo de idioma dañado se omite (no hace que la
aplicación se cierre con un error).

## Requisitos

- Windows 10/11 (64 bits), Python 3.10+ (con la opción tcl/tk)
- Derechos de administrador
- `pydivert` (captura de tráfico), `psutil` (una alternativa, véase más abajo)

La instalación desde el código fuente funciona con Python 3.10 y posteriores. CI prueba y compila
**solo con 3.14**, la versión con la que se congela el `.exe` publicado, de modo que las anteriores
son compatibles, pero no se vuelven a comprobar en cada commit.

En Windows, Python 3.10 a 3.12 miden el tiempo en pasos de 15,6 ms. Cada paquete se cronometra con
ese reloj, así que la latencia, el jitter y los límites de velocidad más finos que un paso salen en
pasos enteros, y `--doctor` avisa de ello. Python 3.13 y posteriores, y el `.exe`, miden en
microsegundos.

`psutil` se instala con la herramienta, pero no es lo que hace posible apuntar a procesos en
Windows. Allí la tabla de sockets y los nombres de los procesos proceden directamente del sistema
operativo, y apuntar a procesos sigue funcionando aunque se elimine `psutil` por completo (medido:
310 puertos asignados, 37 de 37 nombres resueltos). Es la alternativa para todo lo demás, y por eso
las pruebas del motor se ejecutan en Linux sin ningún controlador.

## La ventana

La ventana **se adapta a la pantalla y al escalado del sistema (DPI)**. El tamaño inicial se calcula
a partir de la resolución (cabe en 1366x768 y crece en Full HD / 2K / 4K), y todas las dimensiones
(anchos de columna, alturas de fila de las tablas, márgenes del gráfico, ajuste de texto) se escalan
con la fuente. El programa se declara **compatible con DPI Per-Monitor-V2**, así que mover la
ventana a un segundo monitor con otro escalado no desenfoca la interfaz.

El tamaño y la posición de la ventana, la pestaña seleccionada, el idioma, las secciones plegadas,
la división entre el registro y las pestañas y el orden de las tablas se recuerdan en
`bean_network_tester_ui.json` (junto a los perfiles). La geometría guardada se valida antes de
usarla: una ventana que quedó en un segundo monitor se abre de nuevo allí, y si ese monitor ya no
está, vuelve al centro de la pantalla actual.

- **Control** - todos los ajustes de deterioro, agrupados en **secciones plegables** (el estado
  plegado se recuerda). En una ventana ancha las secciones se disponen **en dos columnas** (en lugar
  de una columna estrecha y una mitad derecha vacía), así que hay mucho menos desplazamiento. Toda
  la pestaña se desplaza, también con la **rueda del ratón**.
- **Statistics** - tres subpestañas, para que nada quede cortado en pantallas pequeñas:
  - **Live** - contadores (paquetes, perdidos, corrompidos, cortados...) y un gráfico de
    rendimiento. La cuadrícula de contadores elige su número de columnas según el ancho de la
    ventana. Un botón "Export CSV".
  - **Session** - semilla, duración, datos usados, picos + los botones "Mark bug", "Save repro
    report" y "Copy CLI command".
  - **Events** - el registro de eventos (START/STOP/CHANGE/SCENARIO/BUG/RESET).
- **Connections** - una vista de con qué IP:puerto habla el sistema probado. Cada columna está
  documentada en [Columnas de Connections](#columnas-de-connections) más abajo, y cada una tiene
  además un tooltip en su encabezado. El tráfico que no tiene puertos, como el ping (ICMP), también
  aparece, con una fila por dirección y las celdas de puerto vacías.
  - **"down"/"up"/"total" son lo que la aplicación recibió realmente**, la misma magnitud que el
    panel de sesión llama "Downloaded (MB)". **"down seen"/"up seen" son lo que la herramienta
    capturó** antes de deteriorar nada. Sin ningún ajuste, son iguales. En cuanto se añade pérdida o
    un límite de velocidad, se separan, y **la diferencia entre ambas es el daño en esa conexión**.
    Al pasar el cursor sobre cualquiera de ellas se ve la frase completa. (Antes de esta separación
    había un solo par, que mostraba los bytes capturados bajo encabezados que significaban
    entregados: una fila podía indicar 5 MB recibidos mientras que su aplicación había recibido
    0,4 MB.) Además hay un cuadro de búsqueda (con retardo antes de actuar, para que la tabla no se
    reorganice a cada pulsación de tecla), encabezados que ordenan con un clic, **"Freeze"** (las
    filas dejan de escaparse de debajo del cursor) y un **menú contextual**: copiar fila / IP,
    **"Target this process"**, **"Limit to this IP:port"**, que rellena los campos del filtro con un
    solo clic. **"Reset this connection"** corta esa conexión al instante, con o sin sesión en
    marcha: el programa que la usa recibe un error y el otro extremo recibe un TCP reset. Durante una
    sesión, ese reset pasa por los deterioros como cualquier otro paquete, de modo que una pérdida
    alta puede descartarlo por el camino. Solo funciona con TCP sobre IPv4 (Windows no tiene forma de
    restablecer una conexión IPv6), por lo que la entrada aparece atenuada en las demás filas, y
    requiere derechos de administrador.
  La tabla está **virtualizada**: dibuja solo las filas que realmente están en pantalla, así que el
  desplazamiento es instantáneo tanto si contiene 400 filas como unos cientos de miles. El antiguo
  límite fijo de 400 filas ha desaparecido: cuántas se muestran se define en el campo **"Row limit"**
  (sección *Tables*, 0 = sin límite, 50 000 por defecto).
- **Tools** - pequeñas utilidades para las preguntas que surgen antes o durante una prueba, una
  subpestaña cada una. Solo **Ping** envía algo por la red en esta pestaña: solicitudes de eco a la
  dirección que se escribe, de Start a Stop. Hoy:
  - **Sockets** - todos los sockets TCP y UDP de este equipo, como `netstat -ano`, sin necesidad de
    sesión: qué está escuchando, qué está conectado, su estado (LISTEN, ESTABLISHED, TIME_WAIT...) y
    el programa que lo posee. Sirve para ver en qué puerto escucha la aplicación antes de
    deteriorarla, o qué programa ocupa un puerto. La tabla se lee al abrir la pestaña y al pulsar
    **Refresh**. Se puede buscar igual que en la tabla de conexiones (`lport:8080`, `state:listen`,
    `proc:chrome`), y con el botón derecho sobre una fila se puede apuntar a su programa, dejarlo en
    paz, o limitar o bloquear su dirección remota. Los nombres de programa se muestran sin derechos
    de administrador.
  - **Port check** - ¿puede su programa usar un puerto? Escriba un puerto, una lista o un rango,
    como se escriben los puertos en la página Control (`8080`, `80, 443`, `9000-9100`, hasta 1000 a
    la vez), y pulse **Check** (o Enter). Cada puerto se comprueba para TCP y UDP, en IPv4 e IPv6, y
    se marca como **Free**, **In use** (con el programa que lo ocupa y su PID) o **Reserved by
    Windows**: un rango que Windows apartó, la razón habitual por la que un servidor no arranca en un
    puerto que parece no usar nadie. Los rangos son por protocolo, así que un puerto puede estar
    libre para UDP y no para TCP. Para cada puerto, la herramienta lo solicita al sistema en la
    dirección de loopback de este mismo equipo y lo devuelve al instante. Quién ocupa un puerto sale
    de la misma tabla que en **Sockets**. Con el botón derecho sobre una fila se puede apuntar al
    programa que ocupa el puerto o dejarlo en paz.
  - **Filter tester** - elija un campo de la página Control (proceso objetivo, IP o puerto de
    destino, IP o puerto bloqueados), escriba una expresión y un valor, y vea de inmediato si
    coinciden. También muestra qué parte de la expresión seleccionó el valor, qué parte con `!` lo
    excluyó y cómo interpreta el programa lo que se escribió. Un valor que no es una dirección, un
    puerto ni un PID se indica como tal, no como "no coincide". **"Use in the Control field"** pone
    la expresión en ese campo, sustituyendo lo que haya. Lo que se escribe se conserva hasta cerrar
    el programa, incluso si se cambia el idioma.
  - **Adapters** - todos los adaptadores de red de este equipo y los ajustes de los que depende una
    prueba, del tipo que imprime `ipconfig /all` (solo Windows). El adaptador por el que sale el
    tráfico de internet aparece arriba, y después los que están activos. Al elegir uno se ven sus
    direcciones con sus prefijos, la puerta de enlace, los servidores DNS, DHCP, la dirección MAC, la
    MTU y la velocidad del enlace. Una nota avisa cuando otro dispositivo usa la misma dirección. La
    lista se lee al abrir la pestaña y al pulsar **Refresh**. Con el botón derecho sobre una puerta
    de enlace o un servidor DNS se pone su dirección en el campo de IP de destino de la página
    Control (el puerto de ese campo se conserva). La primera fila, **Proxy**, muestra si los
    programas pasan por un proxy: los ajustes de esta cuenta (detección automática, un script de
    configuración, un servidor proxy y lo que se salta), el proxy que usan los servicios de Windows
    (WinHTTP) y las variables `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY` y `NO_PROXY`. Un programa que
    usa un proxy se conecta al proxy, no a su objetivo: con el botón derecho sobre el servidor proxy
    se limitan los deterioros a su dirección. Un proxy indicado por nombre no se resuelve, y las
    contraseñas que haya en una dirección se ocultan. **"Copy report"** copia todos los adaptadores y
    los ajustes de proxy en inglés: el texto contiene las direcciones y las direcciones MAC de este
    equipo.
  - **Diagnostics** - por qué START no funciona, sin consola. Ejecuta las mismas comprobaciones que
    `--doctor` (derechos de administrador, el controlador WinDivert, restos en la carpeta
    temporal...) y marca cada una como OK, Warning o Problem. **"Clean up the driver"** descarga un
    controlador WinDivert que se quedó cargado (solo administrador, nunca durante una sesión).
    **"Copy environment report"** copia la línea de `--version` y la salida de `--doctor`, lista para
    pegar en un informe de error. El informe incluye rutas de carpetas, y una ruta puede contener el
    nombre de usuario de Windows. Marque **"Add network adapters"** o **"Add proxy settings"** para
    incluir también en el informe los adaptadores o el proxy: ambas opciones están desactivadas hasta
    que se marquen, porque las direcciones dicen en qué red está este equipo.
- En la parte inferior: **START/STOP**, **Apply changes** y **Load/Save file**, con el registro
  debajo. Esta barra está anclada al borde inferior, así que ninguna pestaña puede taparla.

### Cuándo surten efecto los cambios

**Nada se aplica por sí solo.** Un perfil, un preset, el modo LAN y un archivo de configuración
cargado **solo rellenan el formulario**. Llegan a una sesión en marcha únicamente mediante **"Apply
changes"**: el botón se **resalta** cuando el formulario difiere de lo que el motor está haciendo
realmente. La barra bajo el título indica qué se está viendo:

| Prefijo | Significado |
|---|---|
| `Preview:` | la aplicación está detenida: describe lo que ocurrirá después de START |
| `Active:` | esto es exactamente lo que se está aplicando al tráfico ahora mismo |
| `Unapplied changes:` | se modificó el formulario: haga clic en "Apply changes" |

Mientras una sesión está en marcha, **dos elementos quedan bloqueados** (se desbloquean con STOP): el
**filtro de tráfico** (se aplica solo en START) y el **selector de idioma** (cambiar el idioma
reconstruye toda la interfaz). El botón STOP es rojo, para que no se confunda con START.

Un campo del que se ha adueñado otro ajuste aparece **atenuado junto con su etiqueta**, con una nota
que indica qué ajuste lo ha tomado: "Download"/"Upload" lo hacen cuando hay un Schedule, porque
entonces el rendimiento procede de los pasos de la programación. Se ve de un vistazo qué está
realmente en vigor.

### Atajos de teclado

| Atajo | Acción |
|---|---|
| `F5` | START / STOP |
| `Ctrl+Enter` | Apply changes |
| `Ctrl+S` / `Ctrl+O` | Guardar / cargar el archivo de configuración |
| `Ctrl+L` | Borrar el registro |
| `Ctrl+F` | Búsqueda: la búsqueda de campos en Control, la búsqueda en la tabla de Connections, la búsqueda de sockets en Tools > Sockets |
| `Up` / `Down`, `Page Up` / `Page Down`, `Home` / `End` | En una tabla: mover la selección. Con `Shift`, seleccionar un rango, que puede pasar de una pantalla. `Ctrl+C` copia las filas seleccionadas y `Shift+F10` abre el menú contextual |
| `Enter` / `Tab` / `Escape` | En una ventana de pregunta o de mensaje: `Enter` pulsa el botón resaltado (el predeterminado al abrirse la ventana), `Tab` pasa al botón siguiente, `Escape` la cierra, respondiendo "No" o "Cancel" donde se pregunta |

**Cómo encontrar un ajuste.** El cuadro de la parte superior de la página Control busca los ajustes
por nombre: basta con escribir parte del nombre de un campo o de una sección, o el indicador de la
línea de comandos, como `--loss`. Todas las coincidencias se resaltan y aquella en la que se está se
rellena, de modo que el contador `1 / 4` siempre señala algo visible. `Enter` va a la coincidencia
siguiente, `Shift+Enter` a la anterior, y `Escape` vacía el cuadro. Una sección plegada se abre mientras dura la búsqueda y se pliega de nuevo después. Los acentos son
opcionales. Si lo que se busca es uno de los ajustes que están en la ventana Settings, la
búsqueda lo indica.

### Validación de campos

Los campos numéricos se comprueban **en directo, junto con su rango** (p. ej. pérdida 0-100 %,
latencia 0-600000 ms): un campo incorrecto se pone en rojo y el motivo aparece bajo la sección. Lo
mismo vale para las expresiones de filtro. El mismo rango se aplica en la CLI: `--loss 250` ahora es
un error, no un recorte silencioso a 100 %.

## Todas las opciones explicadas

**Traffic to modify** - qué tráfico capturar. Opciones: ambos sentidos (TCP+UDP+ICMP), solo saliente,
solo entrante, solo TCP, solo UDP, solo ICMP (ping), solo loopback (127.0.0.1/::1, para probar la
comunicación entre procesos locales). Cada filtro abarca **IPv4 e IPv6**. (Si el ping "no
reacciona", casi siempre es porque el filtro elegido no incluye ICMP.)

**El tráfico de loopback cuenta como subida.** Windows entrega ambos sentidos de una conversación
entre dos programas de este equipo como salientes, sea cual sea el filtro elegido. Para ese tráfico,
**Download**, la columna de descarga del programador (schedule) y **NAT timeout** no tienen ningún
efecto, y tampoco los valores principales cuando la subida tiene valores propios. El límite de
**Upload** se aplica a ambos sentidos en conjunto, y un proceso objetivo se ve afectado solo en lo
que envía. Con el filtro de loopback, el programa lo indica cuando se aplican esos ajustes.

> **Nota:** no existen preajustes de puertos ("DNS/HTTP/HTTPS only"). Para acotar por puerto, use el
> campo **Port** de "Target destination", que entiende listas, rangos y exclusiones
> (`80,443,8000-8100`, `!53`). Dos lugares decidiendo sobre los puertos, con semánticas distintas,
> solo causarían confusión.

**Traffic filter** se aplica al iniciar, así que mientras la sesión está en marcha queda
**bloqueado**: para cambiarlo, deténgala (STOP), elija otro e inicie de nuevo (START).

**LAN mode** - una casilla "LAN mode (local network only, no internet)". Rechaza el tráfico desde y
hacia direcciones públicas (de internet) y deja pasar la red local: 10.0.0.0/8, 172.16-31.x,
192.168.x, loopback, enlace local y CGNAT. Simula "la LAN funciona, internet no": una prueba de cómo
se comporta la aplicación sin acceso a internet (p. ej. sin puerta de enlace/WAN, con un portal
cautivo).

**Internet only** - su reverso, una casilla "Internet only (no local network)" en la misma sección.
Descarta el tráfico desde y hacia esas mismas direcciones locales y deja funcionar internet, de modo
que se puede probar una aplicación que habla con un servidor de intranet, un NAS o una impresora
mientras la WAN va bien. Hay dos cosas que no hace, y ambas importan:

- **El loopback sigue funcionando.** 127.x y `::1` pasan en ambos casos, así que un servidor de
  desarrollo local, una base de datos en la propia máquina y cualquier cosa que use el loopback para
  hablar consigo misma quedan intactos. Es deliberado: que la propia máquina hable consigo misma no
  es "la red local".
- **El router está en la red local.** Si el PC pregunta al router por el DNS, la resolución de
  nombres deja de funcionar con él, y entonces internet parece roto aunque el tráfico de internet
  esté pasando. Si eso molesta, use un resolvedor público mientras prueba esto.

Ambas casillas pueden estar activadas a la vez. Está permitido y corta todo salvo el loopback: el
programa lo indica en el registro al aplicarlo, y cada uno de los dos contadores informa de su
propia mitad.

**Target process** - limita el efecto a las aplicaciones elegidas: nombre de proceso (p. ej.
`chrome.exe`), PID, una lista separada por comas, rango de PID, comodín o expresión regular. Véase la
[sintaxis de filtros](#sintaxis-de-filtros-proceso--ip--puerto). El resto del tráfico de la máquina
queda intacto. Campo vacío = todo el tráfico.

**Speed limit** - rendimiento máximo por separado para la descarga (entrante) y la subida
(saliente), en KB/s. 0 = sin límite. El ping son paquetes pequeños, así que un límite de velocidad
apenas lo cambia: para probar el límite, use una descarga de archivo. Un valor positivo siempre
limita algo: un límite extremadamente pequeño (por debajo de 1 B/s) se sube a 1 B/s, no se convierte
silenciosamente en "sin límite".

**Speed unit (Settings window)** - si la página Statistics, el gráfico y el indicador junto a estos
dos campos muestran el rendimiento en `KB/s`, `Mbit/s` o `MB/s`. Cambia lo que se LEE, nunca lo que
se escribe: los propios límites siguen en KB/s, porque es el número que llevan un archivo de
configuración guardado, el programador de rendimiento, los escenarios incluidos, `--down`/`--up` y la
salida NDJSON. Al elegir una unidad aparece un `(= 8.39 Mbit/s)` en gris junto al campo, de modo que
se puede escribir el número que quiere la herramienta mientras se lee el número con el que se vende
el enlace.

> **`K` aquí es 1024, y un megabit es un millón decimal**: las dos convenciones no se compensan, así
> que 1024 KB/s son **8,39 Mbit/s**, no 8. Es la conversión honesta, no un error de redondeo: un
> byte son 8 bits, `1024 x 1024 x 8 = 8 388 608` bits por segundo, y megabit significa 10^6 bits en
> todos los sitios donde se vende un enlace. Divida entre 8,39, no entre 8, cuando quiera que un
> límite coincida con una velocidad anunciada.

**Buffer** - la capacidad del búfer del enlace para un límite de velocidad, en milisegundos
(0 = búfer ilimitado). Fija cuánto retardo de cola puede acumularse en un enlace con la velocidad
limitada antes de que empiece a descartar el exceso (bufferbloat). Sin este búfer, el token bucket
podía "desbocarse" decenas de segundos hacia el futuro: los paquetes llevaban un retardo extremo, y
subir el límite en mitad de una sesión (p. ej. un paso de programación de "el enlace se recupera")
no tenía efecto, porque la acumulación se tragaba todos los pasos más rápidos. Con un búfer de `N`
ms, el retardo queda acotado a ~`N` ms, el exceso se contabiliza como "Rate-limit drop" (un contador
aparte, que no es "Loss" ni "Buffer overflow"), y tras subir el límite el rendimiento se recupera en
~`N` ms. Por defecto 1000 ms. Solo está activo si hay un límite de descarga/subida o una programación
definidos. El tiempo en el búfer se suma a *Latency*, como en un enlace real: con 200 ms de latencia
y un búfer lleno de 150 ms, un paquete llega al cabo de unos 350 ms.

**Delay (ping)** - *Latency*: cuántos ms añadir a cada paquete. *Jitter*: variación aleatoria del
retardo (+/- ms), que hace que el ping salte y que los paquetes se reordenen. Hay tres cosas que
conviene saber:

(0) **El ping sube aproximadamente el doble de la latencia fijada.** El retardo se añade a cada
paquete, y con el filtro de tráfico bidireccional predeterminado eso afecta tanto a la petición como
a la respuesta, de modo que `--latency 100` se manifiesta como unos +200 ms de ping (medido:
`--latency 200` llevó un ping de loopback de menos de 1 ms a ~408 ms). Elija la mitad del ping que
quiera. El jitter **no** se duplica del mismo modo: cada paquete saca su propio valor, así que la
oscilación crece unas 1,4 veces, y llega a 2 solo en los extremos. Los perfiles integrados están
ajustados así: `Satellite (geostationary)` lleva 340 ms y entrega el ping de ~680 ms que tiene un
enlace geoestacionario real.

(1) el jitter añade un retardo aleatorio independiente a cada paquete, de modo que los paquetes
pueden adelantarse unos a otros en la cola: el jitter **reordena paquetes** por naturaleza (una red
real hace lo mismo).
(2) Las oscilaciones negativas se recortan a cero, así que cuando el jitter es **mayor que la
latencia**, el retardo medio añadido sube por encima de la propia latencia (p. ej. con latencia 0 y
jitter 50 ms, aproximadamente la mitad de los paquetes no tiene retardo y la media es de ~12 ms, no
0). Cuando la latencia es mayor que el jitter, el efecto es despreciable.

*Latency spike* está en la misma sección, porque un pico también es latencia: una ocasional grande.
Con la probabilidad dada, añade un retardo extra (ms) a **un solo paquete**, que es como llega en
realidad el "lag" momentáneo. La probabilidad es por paquete y se aplica **en cada sentido**, de
modo que un viaje de ida y vuelta la sufre aproximadamente el doble de veces de lo que sugiere el
número.

**Testing out-of-order delivery** - para esto sirve la pareja de picos, y es la razón por la que la
sección se llama "Latency (ping) and packet order". Un paquete con pico llega después de paquetes
que se enviaron más tarde que él, así que *Spike chance* y *Spike size* reordenan el tráfico **sin**
emborronar el retardo de todos los demás paquetes como hace el jitter, lo cual importa cuando lo que
se prueba es un protocolo UDP que debe sobrevivir por sí mismo al reordenamiento: un juego, QUIC,
telemetría, voz. Fije un tamaño de pico mayor que el intervalo entre sus paquetes, o nada adelantará
a nada.

Si eso ha ocurrido de verdad es una cuestión distinta de si se configuró, así que la herramienta lo
cuenta: **Reordered** en la página Statistics (y `packets_reordered` en el CSV de estadísticas). Un 0
con un pico definido significa que el tráfico era demasiado escaso para que algún paquete adelantara
a otro, no que el ajuste se ignorara. El recuento es por sentido, de modo que dos conexiones
ocupadas pueden adelantarse mutuamente sin que ninguno de los extremos vea nada fuera de orden.

**Impairments** - *Loss*: porcentaje de paquetes que desaparecen sin dejar rastro (un 5 % ya es una
red claramente defectuosa). *Corruption*: porcentaje de paquetes con un bit de datos invertido, que
afecta **solo a los paquetes que llevan carga útil**. Los paquetes sin datos (p. ej. un ACK puro, un
SYN) no tienen nada que invertir, así que pasan intactos y **no se cuentan como corrompidos**.
*Duplication*: porcentaje de paquetes enviados dos veces.

**Losses in a row (burst)** - los enlaces reales rara vez pierden paquetes de uno en uno. Un horno de
microondas, un ascensor o un cambio entre transmisores se llevan la conexión por un instante, y todo
lo que se envía en ese instante se pierde. Este campo indica cuántos paquetes se pierden seguidos
**de media**, mientras que *Loss* sigue decidiendo cuánto se pierde en total. Importa más de lo que
parece: un 5 % repartido es algo que la mayoría de las conexiones absorbe, mientras que ese mismo
5 % en tandas de veinte detiene una transferencia, rompe una conexión activa y manda a la aplicación
por su camino de reconexión. Con 0 la pérdida se reparte de manera uniforme, que es lo que hacía la
herramienta antes de que existiera este ajuste.

Hay dos límites que conviene conocer, y el registro indica ambos al aplicar los ajustes. Una pérdida
muy alta no puede llegar en tandas muy cortas, porque tandas tan cortas dejan muy poco espacio entre
ellas, así que la ejecución indica lo que realmente entregará. Y una tanda larga separa mucho las
tandas, de modo que una sesión corta puede no ver ninguna. Cada sentido tiene sus propias tandas, así
que una tanda de veinte significa veinte seguidos en ese sentido, y con Asymmetry activado el
registro indica ambos límites también para la subida. Con 100 % de pérdida se pierden todos los
paquetes, así que la longitud de la tanda no cambia nada.

**Link flapping** - pérdida total cíclica del tráfico: cada *Period* segundos el enlace está caído
durante el porcentaje de tiempo indicado. Simula una conexión intermitente. Esto **no** es lo mismo
que las pérdidas seguidas: el flapping es un ciclo fijo que se puede predecir, mientras que las
tandas anteriores son aleatorias y cortas, en medio de un tráfico por lo demás normal.

**Advanced (NAT / connections):**
- *Target destination (IP/port)* - deteriora solo el tráfico desde y hacia los servidores elegidos.
  Ambos campos aceptan listas, rangos, CIDR, comodines, comparaciones, exclusiones y expresiones
  regulares. Véase la [sintaxis de filtros](#sintaxis-de-filtros-proceso--ip--puerto). P. ej. IP
  `10.0.0.1-10.0.0.50,!10.0.0.7`, puerto `80,443,8000-8100`. Vacío = cualquiera.
- *TCP SYN drop (%)* - porcentaje de paquetes de apertura de conexión descartados. Simula una
  conexión que no llega a establecerse (pruebas de reintento), útil para pruebas desde detrás de un
  NAT.
- *Max size (MTU)* - descarta los paquetes mayores de N bytes. Reproduce un "agujero negro de MTU"
  de túneles/VPN/detrás de un NAT (los pequeños pasan, los grandes desaparecen). 0 = desactivado.
- *NAT timeout* - si una conexión permanece en silencio más de N segundos, se descarta el siguiente
  paquete entrante (la asignación "desaparece"). Una prueba de keep-alive. 0 = desactivado.
- *TCP tear-down (RST)* - porcentaje de conexiones cortadas bruscamente con un paquete RST. Fuerza
  reconexiones. **Solo TCP** (RST es un concepto de TCP, UDP no se puede "cortar": use pérdida o
  link flapping). El botón **Tear down TCP now** restablece todas las conexiones TCP activas durante
  ~3 s.
- *Schedule* - rendimiento que cambia con el tiempo: `time:download:upload` en KB/s, separado por
  comas. P. ej. `2:100:0, 2:500:0` = 2 s a 100 KB/s, luego 2 s a 500, en bucle. Cuando el Schedule no
  está vacío, **anula** los campos fijos "Download/Upload": la GUI los atenúa y lo dice
  explícitamente. El tiempo de un paso es mayor que 0 y de como máximo 86400 s, y cada velocidad va
  de 0 (sin límite) a 10000000 KB/s, igual que los campos fijos. Un paso fuera de eso se rechaza y se
  nombra.

**Session:**
- *Duration (s)* - pasados estos segundos, el programa **se detiene solo** (exactamente como si se
  pulsara STOP): el deterioro desaparece y el controlador se libera. `0` = funciona hasta STOP (el
  comportamiento anterior, el predeterminado). El equivalente en la CLI es `--duration`. Como el
  filtro de tráfico, se tiene en cuenta **solo en START** ("Apply changes" no lo toca). El valor se
  guarda en el archivo de configuración y en el comando de reproducción.

**Repeatability and scenario:**
- *Seed* - fije cualquier número para que cada ejecución se aleatorice del mismo modo (un error se
  vuelve reproducible). Vacío = distinto cada vez. Se toma **solo en START**, así que queda
  bloqueado mientras una sesión está en marcha.
- *Scenario* - un archivo JSON que cambia ajustes en tiempo real (p. ej. a los 10 s añadir ping, a
  los 20 s cortar). "Loop" lo repite sin fin. Hay ejemplos en `scenarios/` (Wi-Fi de cafetería, móvil
  LTE->3G, VPN congestionada, DNS que falla, servidor de juego sobrecargado, subida interrumpida a
  medias, backend/API bloqueado). "Load scenario...", "Clear" y "Loop" actúan en START, así que
  quedan bloqueados mientras una sesión está en marcha. "Apply changes" durante un escenario
  funciona: véase [Formato del archivo de escenario](#formato-del-archivo-de-escenario).

**Profiles** - preajustes listos **ordenados de mejor (arriba) a peor (abajo)**: Perfect network,
Good Wi-Fi, 5G network, Home DSL (VDSL), LTE/4G, Satellite (low orbit), Distant server (another
continent), Weak Wi-Fi, Cafe (crowded Wi-Fi), Congested home link (bufferbloat), Train/metro
(tunnels), 3G network, Foreign roaming, Satellite (geostationary), In-flight Wi-Fi, 56k modem,
Terrible network, más los propios (guardados con un nombre). El programa **siempre arranca en
"Perfect network"** (no se deteriora nada hasta que se defina algo). Los preajustes integrados no se
pueden borrar: el botón "Delete" está desactivado para ellos.

Los inalámbricos también pierden **en tandas** en lugar de un paquete cada vez, porque eso es lo que
hace un enlace de radio: el desvanecimiento, las interferencias y los traspasos se llevan el canal
durante un rato. Los cableados (DSL, módem de 56k) mantienen su pérdida repartida de manera
uniforme, porque allí la pérdida es una cola llena y no una radio que se va.

Sus cifras proceden de mediciones publicadas siempre que existen (medianas de Ookla® Speedtest® para
satélite y móvil, estudios revisados por pares para la reconfiguración de 15 segundos de Starlink,
para el Wi-Fi en vuelo y para cuántos paquetes Wi-Fi se pierden seguidos). Cada cifra está atribuida
en el bloque de comentarios al principio de `beantester/presets.py`, con los autores, el foro y un
DOI, para poder comprobarla en lugar de fiarse. Donde no existe una cifra así (el "Wi-Fi débil" no
es una magnitud medible), el comentario junto al valor lo dice en lugar de inventar una fuente.
Algunos merecen una frase:

- **Satellite (low orbit)** - modelado sobre Starlink. Su régimen estable es bueno (unos 40 ms de
  ping, 100 Mbit/s). Lo que lo hace distintivo es la reconfiguración cada 15 segundos, que detiene
  brevemente la transmisión y se manifiesta como un pico de latencia ocasional y no como pérdida.
- **Distant server (another continent)** - un enlace rápido en el que no hay nada roto, solo lejano
  (~120 ms de ping). Es el que deja al descubierto los protocolos charlatanes y el código que da por
  hecho que el servidor está en la puerta de al lado.
- **Congested home link (bufferbloat)** - en reposo parece estar bien (20 ms de ping). El deterioro
  es la cola. ⚠️ **Solo muerde cuando la aplicación satura realmente el enlace**, porque el búfer
  forma parte del limitador de velocidad: con un hilo de tráfico de prueba se verá un simple enlace
  de 8 Mbit/s de bajada y 1 Mbit/s de subida, y nada más. Sature la subida de 1 Mbit/s y observe
  cómo el ping sube hacia los dos segundos: el caso de "la videollamada se cae cuando alguien
  empieza una copia de seguridad".
- **Train/metro (tunnels)** - el único preajuste que deja el enlace totalmente caído durante
  segundos seguidos (3 s de cada 30), de modo que la aplicación tiene que **reconectarse**, no
  limitarse a ir más lenta.
- **In-flight Wi-Fi** - el clásico tipo satelital: ~750 ms de ping y 7 % de pérdida, que es la
  mediana medida, no un peor caso. Las aeronaves con equipos de órbita baja más nuevos se comportan
  como "Satellite (low orbit)".

Un perfil guarda **cómo es el enlace**: la pérdida, cuánta llega seguida, la corrupción, la
duplicación, la latencia, el jitter, los picos de latencia, los cortes del enlace (flapping), los
límites de velocidad y el búfer. Todo lo demás (el objetivo, el destino, el bloqueo, RST, MTU, la
caducidad de NAT, el programador, la semilla) queda fuera. Al guardar un perfil se avisa de los que
se tienen activados en ese momento. Use **"Save file..."** para la configuración completa. Elegir un
perfil o un preajuste fija **todos** esos campos a la vez, incluidos los que un preajuste concreto no
menciona: esos vuelven a su valor por defecto, de modo que "Perfect network" significa de verdad
perfecta. Los perfiles guardados por una versión anterior se cargan sin cambios.

En la CLI (`--preset`) se puede indicar un preajuste por su **id canónico** o por un **nombre en
cualquier idioma de la interfaz** (sin distinguir mayúsculas ni diacríticos del polaco:
`"Perfect network"` también funciona). Ids:
`presets.perfect`, `presets.good_wifi`, `presets.5g`, `presets.dsl`, `presets.lte`, `presets.leo`,
`presets.distant`, `presets.weak_wifi`, `presets.cafe`, `presets.bufferbloat`, `presets.metro`,
`presets.3g`, `presets.roaming`, `presets.satellite`, `presets.inflight`, `presets.modem56k`,
`presets.terrible`.

## Sintaxis de filtros (proceso / IP / puerto)

Tres campos, **Target process**, **IP** y **port** (en "Target destination"), hablan el mismo
minilenguaje. La misma sintaxis se usará en cada campo de filtrado que la herramienta incorpore en el
futuro. Funciona de manera idéntica en la GUI y en la CLI (`--target`, `--dst-ip`, `--dst-port`).

### Elementos básicos

| Notación | Significado | Ejemplo |
|---|---|---|
| `a,b,c` | **lista**: coincide cualquiera de los valores | `80,443` |
| `a-b` | **rango**, con ambos extremos **incluidos** | `8000-8100`, `10.0.0.1-10.0.0.50` |
| `>` `<` `>=` `<=` | **comparación** (numérica, en el caso de las IP por el valor de la dirección) | `>1024`, `<=80`, `>10.0.0.5` |
| `!` | **exclusión**: "distinto de" | `!53` |
| `*` `?` | **comodín** (`*` = cualquier secuencia, `?` = un carácter) | `chrome*`, `192.168.1.*` |
| `re:` | **expresión regular** (`re` de Python, sin distinguir mayúsculas) | `re:^chrome\.exe$` |
| `x.x.x.x/n` | **CIDR** (solo en el campo IP) | `192.168.1.0/24`, `2001:db8::/32` |

Un campo vacío = **todo** (sin filtrado). Los espacios alrededor de las comas y de los términos se
ignoran.

### Cómo se combinan los términos

```
matches = (no positive terms OR any positive term matches) AND no "!" term matches
```

Dicho de otro modo: **los positivos suman (OR), las exclusiones restan (AND NOT)**. El orden de los
términos no importa: `80,!53` significa exactamente lo mismo que `!53,80`.

| Entrada | Significa |
|---|---|
| *(vacío)* | todo |
| `443` | solo el puerto 443 |
| `80,443` | solo 80 **o** 443 |
| `!53` | **todo excepto** 53 (no hay ningún término positivo) |
| `!53,!443` | todo excepto 53 y 443 |
| `1000-2000,!1500` | 1000-2000 pero sin 1500 |
| `>1024,!3389` | todo lo que sea mayor que 1024 pero no 3389 |
| `80,443,8000-8100,>9000,!8080` | 80, 443, 8000-8100 y todo lo que sea mayor que 9000, excepto 8080 |

### El campo "Target process"

Un término puede ser un **nombre** o un **PID**, y se pueden mezclar en un mismo campo.

* Un **nombre** (sin `*` y sin `re:`) funciona como una **subcadena sin distinguir mayúsculas**:
  `chrome` encuentra `chrome.exe` **y** `chromedriver.exe`. (Siempre ha funcionado así, y se mantiene
  a propósito para que las configuraciones y los perfiles antiguos sigan funcionando.)
* Un **PID**: un número solo (`12345`), un rango (`1000-2000`) o una comparación (`>1000`).
* Un **comodín** y **`re:`** coinciden con el **nombre** del proceso.
* Las comparaciones `>` `<` `>=` `<=` solo tienen sentido para un **PID** (números). `>chrome` es un
  **error**: la herramienta lo dice explícitamente en lugar de no coincidir en silencio con nada.

```
chrome.exe                     all processes with "chrome.exe" in the name
chrome, !chromedriver          chrome but NOT chromedriver
chrome.exe, firefox.exe        two apps at once
12345                          a specific PID
12345, 6789                    two PIDs
1000-2000                      all processes with a PID in that range
>1000                          all processes with a PID > 1000
firefox*                       a name starting with "firefox"
re:^(chrome|firefox)\.exe$      exactly chrome.exe or firefox.exe
firefox, 12345                 a name and a PID in one field
```

Todos los procesos que coinciden aportan sus puertos locales: el objetivo abarca la **unión** de sus
puertos. El conjunto de puertos se mantiene actualizado durante la sesión a partir de los eventos de
sockets del sistema, de modo que las conexiones nuevas del proceso se detectan en cuanto se abren
(sin un WinDivert real, recurre a volver a examinar la tabla de sockets varias veces por segundo).

**Qué significa "sus puertos locales" en la práctica.** Un paquete lleva direcciones y puertos, nunca
el nombre de un programa, así que la herramienta no puede coincidir directamente con "Chrome". Busca
qué puertos **locales** posee el proceso y hace coincidir cada paquete con su puerto local.

Por eso aquí nunca aparece el `443`. Cuando Chrome carga una página, `443` es el puerto del
**servidor**: el extremo de Chrome en esa conexión es un puerto temporal como `15597`, y ese número
pertenece a un solo proceso a la vez, de modo que su tráfico se detecta con exactitud.

Unos pocos puertos funcionan de otra manera. mDNS (5353), SSDP (1900) y DHCP (67/68) los mantienen
varios programas a la vez, porque así es como los programas encuentran dispositivos en la red. Allí
el número de puerto ya no dice de quién es el tráfico, así que es todo o nada: o se deteriora todo lo
que pasa por ese puerto o no se deteriora nada. El registro lo indica cuando ocurre y nombra cuál de
las dos situaciones se aplica. El tráfico ordinario no se ve afectado.

### El campo "IP"

Se admiten **IPv4 e IPv6**. Una regla nunca coincide con una dirección de la otra familia: una regla
IPv4 no detectará una dirección IPv6 y viceversa (se pueden mezclar sin problema en un mismo campo).

```
1.2.3.4                        one address
1.2.3.4, 8.8.8.8               two addresses
10.0.0.1-10.0.0.50             a range (both ends inclusive)
10.0.0.1-10.0.0.50, !10.0.0.7  a range with a hole
192.168.1.0/24                 a whole subnet (CIDR)
192.168.1.*                    the same via wildcard
!8.8.8.8                       everything except 8.8.8.8
>10.0.0.5                      addresses "greater" than 10.0.0.5
2001:db8::/32                  an IPv6 subnet
2001:db8::1-2001:db8::ff       an IPv6 range
10.0.0.0/8, 2001:db8::/32      IPv4 and IPv6 in one field
re:^10\.                        anything starting with 10.
```

La notación de la dirección no importa: `2001:0db8:0000:0000:0000:0000:0000:0001` y `2001:db8::1` son la
misma dirección para la herramienta.

### El campo "port"

```
443                            one port
80,443                         a list
8000-8100                      a range (both ends inclusive)
>1024                          high ports
<=1024                         privileged ports
!53                            everything except DNS
80,443,8000-8100,!8080         a mix
```

El rango permitido es **0-65535**. `99999` es un error, no se omite en silencio.

### Expresiones regulares (`re:`)

El prefijo `re:` es **obligatorio**: sin él, un término es un valor simple. De ese modo `chrome.exe` es
un nombre de archivo (un punto es un punto), no un patrón de expresión regular.

| Patrón | Encuentra |
|---|---|
| `re:^chrome` | nombres que empiezan por `chrome` |
| `re:^chrome\.exe$` | **exactamente** `chrome.exe` (no `chromedriver.exe`) |
| `re:^(chrome\|firefox)\.exe$` | exactamente `chrome.exe` o `firefox.exe` |
| `re:(node\|python)` | nombres que contienen `node` o `python` |
| `re:^\d+$` | (en un campo de puerto/PID) un número solo |
| `re:^10\.` | (en un campo de IP) direcciones que empiezan por `10.` |
| `!re:^chrome` | **todo excepto** los nombres que empiezan por `chrome` |

Los patrones **no distinguen mayúsculas** y buscan una coincidencia en cualquier posición
(`re.search`): para una coincidencia de principio a fin, use `^` y `$`.

**Una coma dentro de una expresión regular debe escaparse con una barra invertida** (`\,`), porque la
coma separa términos:

```
re:^ch.{1\,8}e\.exe$          correct - {1,8} with a backslash before the comma
re:^ch.{1,8}e\.exe$           WRONG - it is split into "re:^ch.{1" and "8}e\.exe$"
```

### Casos que hacen tropezar

* **`chrome` también encuentra `chromedriver`, pero `chrome.exe` no.** Un nombre simple es una
  *subcadena*: el texto "chrome" aparece en `chromedriver.exe`, pero el texto "chrome.exe" no (allí
  es `chrome` + `driver.exe`). Así que `chrome.exe` -> solo `chrome.exe`. `chrome` -> `chrome.exe`
  **y** `chromedriver.exe`.
* **`chrome*` es más amplio de lo que parece.** El asterisco es "cualquier secuencia", así que
  `chrome*` encuentra `chromedriver.exe` exactamente igual que `chrome`. ¿Se quiere exactamente una
  aplicación? Use `re:^chrome\.exe$` o añada una exclusión: `chrome, !chromedriver`.
* **`8*` en un campo de puerto es un comodín sobre el texto del número**, así que encuentra `8`, `80`,
  `8080` y `8443`, pero **no** `443`. Casi siempre se quería un rango: `8000-8999`. Use los comodines
  de puerto con intención.
* **`80,443,!8080` es simplemente `80,443`.** Una exclusión que no recorta nada no es un error, solo
  es inútil.
* **`!53` también abarca el tráfico sin puerto** (p. ej. ICMP/ping). "Todo excepto 53" significa
  literalmente "todo lo que no es el puerto 53", y un paquete ICMP no es el puerto 53. Si solo se
  quiere TCP/UDP, acote el **Traffic filter**.
* **Un término vacío es un error**, no "todo": `80,,443` y `80,!` se rechazan. Un **campo entero**
  vacío significa "todo".
* **IP y puerto se combinan con AND.** `IP=10.0.0.0/8` + `port=443` significa "tráfico hacia la red
  10.x **y al mismo tiempo** por el puerto 443". ¿Se quiere "uno u otro"? Deje vacío el otro campo y
  haga dos ejecuciones.
* **`>chrome` es un error.** Las comparaciones funcionan con números (PID), no con nombres.
* **`2000-1000` es un error** (rango invertido), no un conjunto vacío.
* **Un comodín no es una expresión regular.** En `chrome*` el asterisco significa "cualquier
  secuencia". En `re:chrome*` significa "la letra `e` repetida 0 o más veces". Si se escribe `re:`,
  se escribe una expresión regular.
* **Una repetición dentro de una repetición se rechaza por demasiado lenta**, por ejemplo
  `re:^(\w+)+$` o `re:^([0-9:]+)+$`. Un patrón así puede tardar segundos con un solo nombre o una sola
  dirección que casi coincide, y una dirección se comprueba en cada paquete. Escriba la repetición una
  sola vez: `re:^\w+$`.

Cada error de sintaxis se notifica **de inmediato**: en la GUI el campo se pone en rojo con el motivo
debajo (en el idioma de la interfaz), y la CLI termina con un `error: ...` legible, nunca con un
silencioso "nada funciona".

## Estadísticas (qué significan los contadores)

El gráfico de rendimiento tiene un eje Y con valores (KB/s), una cuadrícula, una escala redondeada
"bonita" y lecturas actuales de bajada/subida en la esquina. Download/Upload (KB/s en directo),
Packets (cuántos pasaron), Queued (en espera: crece con el retardo/límite), Lost, Loss runs (en
cuántas TANDAS llegó esa pérdida, véase "Losses in a row"), Corrupted, Duplicated, Buffer overflow
(descartados cuando la herramienta está sobrecargada), Dropped at stop (seguían en cola cuando se
pulsó STOP), Send failed (la herramienta los capturó pero no pudo devolverlos a la red: la conexión
se cayó o el controlador los rechazó), Rate-limit drop (descartados por un búfer de límite de
velocidad lleno, contados aparte de la pérdida y de "Buffer overflow"), SYN dropped, MTU dropped, NAT
expired, RST torn, LAN: internet cut off, Local network cut, RST sent.

**Copiar las cifras.** Haga clic con el botón derecho en cualquier valor de "Live" o "Session" para
copiar ese valor o la pestaña completa. Cada panel tiene además un botón ("Copy counters" bajo la
cuadrícula, "Copy session details" junto a los botones de reproducción) que copia cada fila
exactamente como se lee en pantalla, con sus títulos y unidades. Resulta práctico para un informe de
error: el panel de sesión incluye el nombre del equipo, sus direcciones, la semilla y lo que abarcó
la captura.

Los tres últimos de esa lista ("Buffer overflow", "Dropped at stop" y "Send failed") son la
herramienta perdiendo paquetes, no el enlace que se le pidió simular. Se cuentan, mantienen honesta
la aritmética de visto/entregado/descartado y, a propósito, **no** forman parte de "Effective loss".
Si cualquiera de ellos es distinto de cero, parte de la pérdida que se está midiendo es nuestra.

### Reproducir un error (el panel "Session and reproduction")

Diseñado para que, tras un error, se puedan recrear exactamente las mismas condiciones:

- **Seed (effective)** - aunque se deje vacío el campo Seed, el programa sortea y recuerda una semilla
  concreta. Escríbala más tarde en el campo Seed y vuelva a ejecutar para obtener los mismos
  sorteos.
- **Repeatable flapping** - el patrón de cortes del enlace se mide desde el inicio de la sesión, de
  modo que con los mismos ajustes se repite de forma idéntica entre ejecuciones (no depende del reloj
  del sistema).
- **What the seed reproduces** - la semilla reproduce las **decisiones** del motor (qué paquetes se
  descartan, se corrompen, se duplican, cuánto se retrasan), no el **número de paquetes**. El tráfico
  que cruza el enlace depende de lo que hagan las aplicaciones y el sistema en ese momento, así que
  dos ejecuciones con la misma semilla dan las mismas *proporciones* (p. ej. 15,8 % de pérdida en
  ambas), pero no contadores idénticos al paquete. Para comparaciones en CI, use tasas (%), no
  recuentos brutos de paquetes.
- **Start / Duration / Effective loss / Queue peak / Down-up peak** - una imagen rápida de la
  ejecución.
- **What "Effective loss" counts** - la proporción del tráfico al que se apuntó que **esta
  herramienta** rompió, a través de **todos** los deterioros: el Loss configurado más los descartes
  por límite de velocidad, el bloqueo, el corte de LAN, el corte de la red local, los cortes del
  enlace, los restablecimientos de conexión, los descartes de SYN, los descartes de MTU y la
  caducidad de NAT. Con un objetivo definido, solo cuenta el tráfico del objetivo, de modo que otras
  aplicaciones no pueden diluirlo. Los paquetes que descartó la **herramienta** quedan excluidos a
  propósito: "Buffer overflow", "Dropped at stop" y "Send failed" son fallos suyos, no del enlace, y
  tienen sus propios contadores. El `effective_loss_pct` del informe es el mismo número, junto a
  `packets_in_scope`.
- **Driver queue wait (peak)** - lo más que un paquete llevaba **ya** esperando dentro de WinDivert
  cuando esta herramienta lo recibió. Se mide, no se estima: el controlador marca cada paquete con
  una hora de captura, y la herramienta lo muestrea 20 veces por segundo. En una máquina ociosa es
  una fracción de milisegundo (medido aquí: 0,05-0,16 ms). Si crece, la herramienta está añadiendo
  retardo que no aparece en ningún otro contador, porque ocurre en la cola del controlador, antes de
  la suya, y cuando llega a 50 ms lo dice en el registro y en la lista de eventos. En blanco con
  `--simulate`, que no tiene controlador.
- **It measures this machine, not the internet.** La herramienta ve los paquetes que cruzan la pila de
  red de este equipo, así que un paquete perdido fuera, en la red (la respuesta que nunca volvió),
  nunca llega aquí y nada aquí puede contarlo. Un ping limpio de 30 paquetes que pierde una respuesta
  muestra **59** paquetes en la fila de la conexión y **cero** descartes, y ambos números son
  correctos: salieron 30 peticiones, volvieron 29 respuestas y la herramienta no rompió ninguna. La
  pérdida de extremo a extremo es para lo que sirven las cifras de la propia aplicación (o el "Lost"
  de `ping`).
- **Data used** - Downloaded / Uploaded / Total (MB) acumulados desde el inicio, más el rendimiento
  medio de la sesión. Se sabe de inmediato cuántos datos usó la aplicación. (El informe también tiene
  "attempted MB": cuánto quería enviar la aplicación antes de restar las pérdidas y los límites.)
- **Event log** con marcas de tiempo: inicio, cambios de ajustes, pasos del escenario, cortes y los
  marcadores de error del usuario, con **ordenación** al hacer clic en el encabezado de una columna.
- **Mark the moment of a bug** - haga clic justo cuando vea el error. Inserta en el registro un
  marcador con marca de tiempo.
- **Save reproduction report** - un único archivo JSON con todo: semilla, todos los ajustes,
  contadores, métricas, registro de eventos, conexiones y un **comando de CLI listo** que recrea las
  condiciones. También registra **la cola de WinDivert detrás de la que se ejecutó la sesión**
  (`session.driver_queue`: longitud, tiempo y tamaño). Es el búfer propio del controlador, anterior
  al de esta herramienta, y los tres valores son techos, no un retardo fijo: mientras la herramienta
  va al ritmo, los paquetes apenas esperan en ella (véase **Driver queue wait (peak)** más arriba).
  Solo se llena cuando la herramienta se queda atrás. Entonces los paquetes esperan más, y cuando se
  llena del todo el controlador los descarta antes de que esta herramienta los vea. Una cola menor no
  eliminaría esa espera, la convertiría en paquetes perdidos que ningún contador puede mostrar, así
  que la herramienta deja en paz los ajustes propios del controlador. Un informe de una máquina que
  no se tiene delante dice qué cola produjo sus números. Los mismos tres valores van al registro en
  START.
- **Copy CLI command** - directamente al portapapeles: `BeanNetworkTester.exe --seed ... --loss ...
  --duration ...` (el comando se adapta a la compilación: desde el repositorio se obtiene
  `python bean_network_tester.py ...`).
- **What the report and the command describe** - la última sesión, no el formulario: los ajustes que
  le dio START, actualizados por cada "Apply changes", con su semilla y su escenario (`--scenario`,
  más `--loop` si se repitió en bucle). Un cambio que se escribió pero no se aplicó queda fuera, y lo
  mismo ocurre con un perfil cargado después de STOP. Durante un escenario, "Apply changes" pasa a
  ser la base sobre la que se construyen sus pasos posteriores, así que el comando también recoge
  esos ajustes. Un escenario que viene con el programa se nombra a partir de la carpeta del programa
  (`scenarios\...` desde el código fuente, `_internal\scenarios\...` junto al `.exe`), y el comando lo
  encuentra desde cualquier carpeta en la que se ejecute. Cualquier otro archivo se nombra con la ruta
  elegida. Antes de la primera sesión, **Copy CLI command** copia los ajustes del formulario.

## Archivo de configuración

Los botones "Save/Load file" escriben todos los ajustes en JSON. El mismo archivo funciona en la CLI
mediante `--config`. Orden de precedencia: valores por defecto < archivo < preajuste < indicadores.

Cada valor se comprueba según su tipo al leer el archivo, y un paso de escenario se comprueba del
mismo modo. Un interruptor (`lan_mode`, `internet_only`, `narrow_filter`...) es `true` o `false`, o
bien `1` o `0`. El texto `"false"` se rechaza, no se lee como "activado". `filter` es una de las
opciones de `--filter`, y `seed` es un número entero (`-1` para uno aleatorio). Un valor de tipo
incorrecto detiene la CLI con el código `3` y nombra el ajuste. La ventana muestra el mismo mensaje
y deja el formulario como estaba.

## Modo de línea de comandos (CLI)

La CLI se ejecuta **desde el mismo `BeanNetworkTester.exe`** que la GUI: al iniciarlo con cualquier
argumento arranca el modo de texto (sin ventana, sin tkinter), y sin argumentos arranca la GUI. Los
mensajes y `--help` están siempre en inglés.

```bat
:: GUI
BeanNetworkTester.exe

:: CLI (from the same exe)
BeanNetworkTester.exe --loss 5 --latency 100 --down 1024 --target chrome.exe
BeanNetworkTester.exe --preset "3G network" --duration 60
```

> ¿Se trabaja desde el repositorio (sin compilar)? Sustituya en todas partes `BeanNetworkTester.exe`
> por `python bean_network_tester.py`: todos los indicadores y códigos de salida son idénticos.

### Códigos de salida (el contrato de CI/CD)

Cada forma de terminar tiene su propio código, así que un pipeline no necesita analizar texto:

| Código | Nombre | Cuándo |
|---|---|---|
| `0` | ok | la sesión se ejecutó y todas las comprobaciones se superaron |
| `1` | runtime | no se pudo iniciar (falta `pydivert`, el controlador, fallo del motor) |
| `2` | usage | línea de comandos incorrecta (indicador desconocido, tipo erróneo): el código de argparse |
| `3` | config | ajustes no válidos: expresión, programación, rango, preajuste, archivo de configuración |
| `4` | scenario | el archivo de escenario no existe o está mal formado |
| `5` | io | no se pudo escribir un artefacto (informe de reproducción, configuración guardada) |
| `6` | assertion | la ejecución tuvo éxito, pero `--min-packets` / `--fail-on-no-traffic` no se cumplió |
| `7` | permission | se necesitan derechos de administrador y faltan |
| `130` | interrupted | Ctrl+C (SIGINT) |
| `143` | terminated | SIGTERM (cancelación de un job, `docker stop`), Ctrl+Break o cierre de la ventana de la consola |

`BeanNetworkTester.exe --help` imprime los mismos códigos.

### Salida: registros en stderr, datos en stdout

- **stderr** - el registro para personas, con el prefijo `[bean]` (inicio, semilla, errores, motivo
  de la parada),
- **stdout** - datos: líneas de informe y, con `--format json`, **NDJSON** (un objeto JSON por línea:
  sucesivos objetos `sample` y un `summary` final con el código de salida, la semilla y el comando de
  reproducción).

```bat
BeanNetworkTester.exe --simulate --duration 30 --format json > run.ndjson
```

### Todos los parámetros de la CLI

**Deterioro del enlace**

| Opción | Unidad | Descripción |
|---|---|---|
| `--loss` | % | porcentaje de paquetes descartados |
| `--loss-burst` | paquetes | número medio de paquetes perdidos seguidos (0 = pérdida repartida uniformemente). Da forma a `--loss`, no se suma a él |
| `--corrupt` | % | porcentaje de paquetes con un bit invertido |
| `--dup` | % | porcentaje de paquetes enviados dos veces |
| `--latency` | ms | retardo fijo añadido a cada paquete |
| `--jitter` | ms | variación aleatoria del retardo (+/-) |
| `--down` `--up` | KB/s | límite de rendimiento (0 = sin límite) |
| `--buffer` | ms | búfer del enlace para el límite de velocidad (0 = sin límite). Acota el retardo de cola, el exceso se contabiliza como "Rate-limit drop" |
| `--spike-prob` `--spike-ms` | % / ms | con la probabilidad dada, añade un retardo extra |
| `--syn-drop` | % | porcentaje de paquetes TCP SYN descartados |
| `--max-size` | B | "agujero negro de MTU": descarta los paquetes mayores de N bytes (0 = desactivado) |
| `--nat-timeout` | s | tras N s de silencio, la asignación de NAT "desaparece" (0 = desactivado) |
| `--rst-prob` `--rst-cooldown` | % / s | porcentaje de conexiones cortadas con RST y durante cuánto tiempo se mantiene el corte |
| `--flap-period` `--flap-down` | s / % | corte cíclico del enlace: con qué frecuencia y durante qué fracción del periodo |
| `--rate-schedule` | - | rendimiento cambiante: `"time:download:upload,..."` en KB/s, en bucle. Tiempo mayor que 0 y de como máximo 86400 s, velocidades de 0 (sin límite) a 10000000 |
| `--asym` | - | da a las subidas sus propios valores. Sin él, un único conjunto de números se aplica en ambos sentidos, que es lo predeterminado |
| `--loss-up` `--corrupt-up` `--dup-up` | % | los mismos tres deterioros, para los paquetes que este equipo ENVÍA. Se usan solo con `--asym` |
| `--latency-up` `--jitter-up` | ms | el retardo y su variación, para los paquetes que este equipo ENVÍA. Se usan solo con `--asym` |
| `--spike-prob-up` `--spike-ms-up` | % / ms | el retardo ocasional más largo, para los paquetes que este equipo ENVÍA. Se usan solo con `--asym` |
| `--ipv4-only` `--ipv6-only` | - | deteriora solo una familia de direcciones. La otra sigue circulando sin tocar: esto apunta la herramienta, no bloquea un protocolo. También funciona con `--dst-ip` vacío, que significa todas las direcciones. Si se usan ambos indicadores a la vez se excluyen mutuamente, no se deteriora nada, y el registro lo dice |
| `--lan-mode` | - | modo LAN: corta internet (direcciones públicas) y conserva la red local |
| `--internet-only` | - | el reverso: corta la red local (10.x, 172.16-31.x, 192.168.x, enlace local, CGNAT) y conserva internet. El loopback sigue funcionando. Cuidado: el DNS que se pregunta al router es tráfico local, así que internet puede dejar de funcionar con él |
| `--narrow-filter` | - | introduce `--dst-ip`/`--dst-port` en el filtro de WinDivert para que el controlador nunca entregue tráfico que no podría deteriorarse (mucho más rápido con tasas altas de paquetes). Solo en START. Mientras está activado, las estadísticas y las conexiones cubren solo el tráfico acotado |

**Selección del objetivo** (los tres aceptan la [sintaxis de filtros](#sintaxis-de-filtros-proceso--ip--puerto)
completa: listas, rangos, `!`, `>`, `<`, `>=`, `<=`, comodines, `re:`, y `--dst-ip` además CIDR)

| Opción | Descripción | Ejemplos |
|---|---|---|
| `--target` | procesos: nombre, PID, rango de PID, comodín, expresión regular | `--target chrome.exe`<br>`--target "chrome,!chromedriver"`<br>`--target ">1000"` |
| `--dst-ip` | direcciones IP remotas (IPv4 e IPv6) | `--dst-ip 1.2.3.4`<br>`--dst-ip "10.0.0.1-10.0.0.50,!10.0.0.7"`<br>`--dst-ip "192.168.1.0/24"`<br>`--dst-ip "2001:db8::/32"` |
| `--dst-port` | puertos remotos (0-65535) | `--dst-port 443`<br>`--dst-port "80,443,8000-8100"`<br>`--dst-port "!53"`<br>`--dst-port ">1024"` |
| `--filter` | qué tráfico capturar (IPv4 + IPv6): `both,out,in,tcp,udp,ping,loopback` | `--filter tcp` |

**Bloqueo (cortafuegos)** - descarta todo el tráfico hacia los destinos elegidos. El bloqueo se activa por **IP O puerto** (un campo vacío se ignora, así que `--block-port 443` por sí solo bloquea el 443 hacia cualquier dirección). La misma [sintaxis de filtros](#sintaxis-de-filtros-proceso--ip--puerto) de arriba. Respeta la selección de procesos (bloquea solo el tráfico del objetivo).

| Opción | Descripción | Ejemplos |
|---|---|---|
| `--block-ip` | bloquea direcciones IP remotas (IPv4 e IPv6) | `--block-ip 1.2.3.4`<br>`--block-ip "10.0.0.0/8,!10.0.0.1"` |
| `--block-port` | bloquea puertos remotos (0-65535) | `--block-port 443`<br>`--block-port "80,443,8000-8100"` |
| `--block-reject` | rechaza las conexiones TCP bloqueadas en lugar de descartarlas en silencio | `--block-port 443 --block-reject` |

**Rechazado o ignorado** - por defecto, una conexión bloqueada no recibe ninguna respuesta, y el
programa que se está probando espera hasta que se rinde por sí solo. Con `--block-reject` se rechaza
en su lugar, de modo que el programa informa de "connection refused" en unos dos segundos, igual que
lo haría con un puerto realmente cerrado. Son dos caminos de código distintos en la mayoría de las
aplicaciones, y un conjunto de pruebas que solo vio uno de ellos solo ha probado uno de ellos. El
rechazo abarca las **conexiones que inicia este equipo, por TCP**: el tráfico por UDP y las
conexiones que llegan desde fuera se siguen bloqueando en silencio.

> En `cmd.exe`/PowerShell, **ponga la expresión entre comillas** si contiene una coma, `!`, `>`, `<`,
> `*` o `^`: de lo contrario, el intérprete la interpreta a su manera (`cmd.exe` elimina un `^`
> suelto, así que `re:^edge` llegaría como `re:edge`). El comando que recrea la sesión
> (`Copy CLI command` y la línea `Reproduce:`) los pone entre comillas automáticamente.

**Ejecución e informes**

| Opción | Descripción |
|---|---|
| `--preset NAME` | preajuste por id canónico o por un nombre en cualquier idioma de la interfaz |
| `--config FILE` / `--save-config FILE` | cargar / guardar ajustes (JSON, compartido con la GUI) |
| `--scenario FILE` `--loop` | un escenario de línea de tiempo (JSON) y su repetición en bucle |
| `--seed N` | semilla de aleatoriedad: la misma ejecución se puede repetir |
| `--duration N` | **tiempo de ejecución en segundos** (0 = hasta Ctrl+C, o hasta que se agota la línea de tiempo de un `--scenario`). El mismo campo está en la GUI ("Session") |
| `--row-limit N` | un ajuste **solo de la GUI**: máximo de filas en las tablas (0 = sin límite, 50 000 por defecto). En la CLI sin ventana no hace nada: solo se guarda en el archivo de configuración y surte efecto cuando esa configuración se abre en la GUI. El equivalente del campo "Row limit" |
| `--interval N` | cada cuánto informar, en segundos (mayor que 0, como máximo 86 400: el mismo tope que tiene `--duration`, así que un intervalo que nunca podría activarse se rechaza en lugar de aceptarse) |
| `--log-conns` | imprime las conexiones observadas al final |
| `--repro-out FILE` | guarda un informe de reproducción (JSON) |
| `--simulate` | tráfico sintético en lugar de WinDivert (prueba sin Windows, sin controlador, sin administrador) |
| `--gui` | abre la GUI. Válido **solo por sí mismo**: la GUI tiene sus propios controles, así que combinarlo con indicadores de ajustes es un error de uso (exit 2) y no una ejecución silenciosa sin ventana |
| `--version` | imprime la versión y termina |

**Salida y diagnóstico**

| Opción | Descripción |
|---|---|
| `-v`, `--verbose` | registra lo que hace el programa: ajustes efectivos, filtros compilados, puertos de procesos resueltos, pasos del escenario, apertura/cierre del controlador |
| `-q`, `--quiet` | solo errores: sin registro ni informes periódicos |
| `--log-level {error,warn,info,debug}` | nivel de registro explícito (anula `-v`/`-q`) |
| `--log-file FILE` | añade también el registro (y los informes) a un archivo: un artefacto listo para CI |
| `--format {text,json}` | formato de stdout: texto para personas o NDJSON para un pipeline |

**Para CI/CD**

| Opción | Descripción |
|---|---|
| `--dry-run` | comprueba la configuración y termina (no toca el controlador, no deja pasar tráfico): ideal para validar archivos de configuración en un pipeline. Un `--scenario` también se lee y se valida, de modo que la ejecución en seco y la real coinciden |
| `--print-config` | imprime los ajustes efectivos (tras `defaults < file < preset < flags`) como JSON y termina |
| `--min-packets N` | termina con el código `6` si se capturaron menos de N paquetes |
| `--fail-on-no-traffic` | atajo de `--min-packets 1`: **detecta un filtro que no capturó nada** |
| `--doctor` | comprueba el entorno (administrador, `pydivert`, estado del controlador WinDivert, restos en `%TEMP%`, si se puede escribir en la carpeta del programa sin derechos de administrador, con qué finura mide el tiempo el reloj) y termina |
| `--cleanup-driver` | descarga un controlador WinDivert atascado (libera el archivo `.sys` bloqueado **sin reiniciar el sistema**) y termina. Cada línea dice qué ocurrió con un servicio. El código de salida es `0` incluso cuando un servicio no se pudo detener |

Orden de precedencia: **defaults < `--config` < `--preset` < flags**. Lista completa:
`BeanNetworkTester.exe --help`.

### Ejemplos de selección del objetivo

```bat
:: only the browser, but not its test driver
BeanNetworkTester.exe --loss 10 --target "chrome,!chromedriver"

:: only HTTPS traffic to a test server and its backup address
BeanNetworkTester.exe --latency 300 --dst-ip "10.0.0.5,10.0.0.9" --dst-port 443

:: the whole test subnet except one host, on application ports
BeanNetworkTester.exe --down 128 --dst-ip "10.0.0.0/24,!10.0.0.1" --dst-port "8000-8100"

:: everything EXCEPT DNS (so name resolution works while the rest breaks)
BeanNetworkTester.exe --loss 20 --dst-port "!53"

:: high-PID processes, traffic to IPv6
BeanNetworkTester.exe --jitter 80 --target ">1000" --dst-ip "2001:db8::/32"
```

### Ejemplos de bloqueo (cortafuegos)

```bat
:: cut the app off from an external API (the server is "down")
BeanNetworkTester.exe --block-ip 203.0.113.10

:: block all HTTPS - see how the app copes with no connection
BeanNetworkTester.exe --block-port 443

:: block several ports OR the whole backend subnet (blocking is IP OR port)
BeanNetworkTester.exe --block-port "8080,9090" --block-ip 203.0.113.0/24

:: impair only your app's traffic, and cut its link to the payment server entirely
BeanNetworkTester.exe --latency 200 --target myapp.exe --block-ip 198.51.100.7
```

### El modo `--simulate` (prueba sin Windows y sin administrador)

Una vista previa con tráfico sintético: no necesita ni WinDivert ni privilegios:

```bat
BeanNetworkTester.exe --simulate --down 500 --loss 10 --duration 4 --interval 1
```

### Repetibilidad y escenarios desde la CLI

```bat
BeanNetworkTester.exe --simulate --seed 42 --loss 20 --duration 10
BeanNetworkTester.exe --simulate --scenario scenarios/cafe-wifi.json
```

`scenarios/<name>.json` (o `_internal\scenarios\<name>.json`) abre desde cualquier carpeta un
escenario que viene con el programa. Si la carpeta actual tiene un archivo en esa ruta, se usa ese
archivo.

La semilla garantiza **decisiones por paquete** idénticas para la misma secuencia de paquetes. Los
pasos del escenario son acumulativos (cada uno modifica el estado), y `action: reset_tcp` corta las
conexiones TCP en ese momento. El archivo de escenario se **valida al abrirlo**: un JSON cualquiera
termina con un error legible, no con un "escenario con 0 pasos", y los ajustes de un paso se
comprueban con las mismas reglas que usa el formulario, de modo que un valor que el programa no puede
usar se nombra con su número de paso en lugar de detener la ejecución a medias.

Cada ejecución de la CLI termina imprimiendo la **semilla efectiva** y un comando listo para
reproducirla (con el archivo de `--scenario` tal como se escribió, y `--loop` y `--simulate` cuando
la ejecución los tenía), y `--repro-out file.json` guarda el informe de reproducción completo con el
mismo comando.

## Columnas de Connections

Diecisiete columnas, todas ordenables haciendo clic en el encabezado, y cada una con la misma
explicación como tooltip en ese encabezado.

| columna | qué contiene |
|---|---|
| `process` | El proceso que posee el puerto local. `?` significa que no se pudo resolver el nombre: ejecute como administrador. |
| `PID` | Id del proceso que posee el puerto local, resuelto en el momento en que se capturó el paquete. |
| `proto` | Protocolo de transporte: TCP / UDP / ICMP / IP. |
| `remote IP` | La dirección con la que habla este equipo. Con el botón derecho sobre una fila se limitan los deterioros a ella. |
| `r.port` | Puerto del lado remoto (443 = HTTPS, 53 = DNS, 80 = HTTP). Vacío en el tráfico sin puertos, como el ping. |
| `l.port` | Puerto de este equipo: lo que enlaza la conexión con un proceso. Vacío en ping/ICMP, que es también la razón por la que esas filas no suelen tener nombre de proceso. |
| `packets` | Paquetes vistos en esta conexión desde que apareció. |
| `impaired?` | Si la conexión estuvo **dentro del alcance del deterioro** en esta sesión: deteriorada, no meramente observada. Sigue en `yes` después de que la conexión se cierre, como registro. Sin ninguna selección de objetivo, todo está dentro del alcance. |
| `dropped` | Paquetes descartados en esta conexión por los deterioros activos (pérdida, corte del enlace, modo LAN, "Internet only", restablecimientos, ...). |
| `down` | Datos que realmente **llegaron** a la aplicación: lo que descargó. La misma magnitud que el panel de sesión llama "Downloaded (MB)". |
| `up` | Datos que realmente **salieron** de este equipo: lo que subió la aplicación. |
| `total` | Descarga entregada + subida entregada. |
| `down seen` | Datos que la herramienta **capturó** al entrar, antes de cualquier deterioro: lo que ofrecía la conexión. |
| `up seen` | Datos que la herramienta **capturó** al salir: lo que la aplicación intentó enviar. |
| `avg[B]` | Tamaño medio de paquete en esta conexión (bytes totales / paquetes). |
| `time[s]` | Segundos entre el primer y el último paquete de esta conexión en esta sesión. |
| `idle[s]` | Segundos desde el último paquete. Deja de contar cuando la sesión se detiene. |

**Las cinco columnas de tráfico llevan su propia unidad.** Cada celda se muestra en la unidad que le
corresponda entre B, KB, MB o GB, de modo que un flujo de 5 GB se lee `5.00 GB` en lugar de
`5242880.0` y una respuesta DNS de noventa bytes se lee `90 B` en lugar de `0.0`. El pie bajo la tabla
hace lo mismo con sus totales. `avg` es un tamaño de paquete y se queda en bytes. La ordenación y la
exportación a CSV no se ven afectadas: ambas trabajan con los recuentos de bytes en bruto, nunca con
el texto de la celda.

**El par entregado/visto es el sentido de la tabla.** Sin nada deteriorado, son iguales. Con pérdida o
un límite de velocidad se separan, y **la diferencia entre ambos es el daño causado a esa conexión**.
(Antes de separarlos había un solo par, que mostraba los bytes capturados bajo encabezados que
significaban entregados: una fila podía indicar 5 MB recibidos mientras su aplicación recibió 0,4 MB.)

## Exportaciones a CSV

Dos botones escriben dos archivos, y se comportan **de forma distinta a propósito**. Ambos van a la
carpeta propia del usuario, `%LOCALAPPDATA%\BeanNetworkTester`, junto con los perfiles y el estado de
la ventana (o a la raíz del proyecto cuando se ejecuta desde el código fuente). El programa escribe
la ruta completa en el registro cada vez que guarda uno. Se mantienen fuera de la carpeta del
programa para que actualizarlo, a mano o mediante un gestor de paquetes que reemplaza esa carpeta, no
pueda llevarse los archivos consigo. Defina `BEAN_DATA_DIR` con una carpeta a su elección para
guardarlo todo en otro sitio, por ejemplo en el mismo pendrive que una copia portátil.

La carpeta pertenece a la cuenta de Windows con la que se ejecuta el programa. En una cuenta sin
derechos de administrador, aceptar el aviso de elevación ejecuta el programa como la cuenta de
administrador cuya contraseña se introdujo, y entonces usa la carpeta de ESA cuenta, así que los
perfiles guardados sin elevación no son los que se ven con ella. "About" y `--doctor` imprimen ambos
la carpeta en uso, de modo que siempre se puede saber cuál se está mirando. Para dar a todas las
cuentas del equipo una única carpeta compartida, un administrador puede definir `BEAN_DATA_DIR` como
variable de entorno de todo el sistema.

| | **Statistics** ("Export CSV", Statistics -> Live) | **Connections** ("Export connections CSV") |
|---|---|---|
| archivo | `bean_network_tester_stats.csv` | `bean_network_tester_connections.csv` |
| modo | **Añade** una fila por clic: un registro con el que se puede construir un gráfico a lo largo de varias ejecuciones | **Sobrescribe**: una instantánea de la tabla tal como está ahora |
| escritura | atómica (archivo temporal + renombrado), así que un fallo a mitad de la escritura no puede truncarlo | igual |
| su búsqueda / ordenación | no se aplica | **se respeta**: el archivo coincide con lo que se estaba viendo |
| "Show only the targeted traffic" | **se ignora a propósito**: véase más abajo | **se respeta** |
| el campo "Row limit" | no se aplica | **se ignora**: se exportan todas las filas filtradas, no solo las dibujadas |
| las columnas cambian entre versiones | el archivo antiguo se renombra con una marca de tiempo y se empieza uno nuevo, para que las filas nunca queden desalineadas bajo un encabezado obsoleto | no se aplica |
| codificación | UTF-8 sin marca de orden de bytes. Al abrirlo con doble clic, Excel lee un archivo así en la página de códigos de Windows y estropea las letras que quedan fuera de ella (nombres de procesos en polaco o chino). Ábralo mediante **Data > Get Data > From File > From Text/CSV** y establezca **File Origin** en **65001: Unicode (UTF-8)** | igual |

El CSV de estadísticas no respeta el interruptor "show only the targeted traffic" porque es un
registro en el que se añaden filas: un archivo cuyas columnas significan una cosa en unas filas y otra
en el resto es peor que inútil para la hoja de cálculo para la que existe. En su lugar lleva **ambos**
totales (`bytes_in`/`bytes_out` y `delivered_in_scope_bytes_*`), de modo que se puede acotar por
cuenta propia y seguir viendo cuál es cuál. **"Capture only the targeted traffic" no se puede
deshacer así**, porque cambia lo que contó `packets_seen` en primer lugar, y por eso cada fila lo
registra en `capture_narrowed`.

### Columnas del CSV de estadísticas

`time`, el alcance de captura de la sesión, y después todos los contadores, en este orden:

| columna | significado |
|---|---|
| `time` | hora del reloj en el momento del clic |
| `capture_narrowed` | `yes` cuando "Capture only the targeted traffic" estaba activo en esa sesión, de modo que todos los recuentos de la fila cubren **solo** el tráfico de su destino. `no` significa que la fila cubre todo lo que dejó pasar el filtro de tráfico. Sin esta columna, dos filas con el mismo `packets_seen` podrían describir un tráfico completamente distinto |
| `packets_seen` | paquetes capturados |
| `packets_in_scope` | de ellos, los que el objetivo seleccionó para deteriorar |
| `dropped_loss` | descartados por el ajuste Loss |
| `loss_runs` | en cuántas TANDAS llegó esa pérdida (véase "Losses in a row"). 0 con una longitud de tanda definida significa que la sesión fue demasiado corta para ver una, o que la pérdida es del 100 % y no hay tandas separadas |
| `dropped_overflow` | descartados porque la cola propia de la herramienta estaba llena (véase la nota sobre ello más abajo) |
| `corrupted` | paquetes cuya carga útil se invirtió |
| `duplicated` | copias extra puestas en cola |
| `packets_reordered` | paquetes que salieron de la herramienta en un orden distinto al de entrada. 0 con jitter o un pico configurados significa que los paquetes estaban demasiado separados para que alguno adelantara a otro. Se cuenta por sentido, así que dos conexiones ocupadas pueden adelantarse mutuamente sin que ninguno de los extremos vea nada fuera de orden |
| `dropped_syn` | TCP SYN descartados ("conexiones que nunca se abren") |
| `dropped_mtu` | descartados por superar el tamaño máximo (agujero negro de MTU) |
| `dropped_nat` | descartados porque la asignación de NAT había caducado |
| `dropped_rst` | tráfico absorbido mientras una conexión se mantenía caída tras un reset |
| `dropped_lan` | descartados por el modo LAN (internet cortado, red local viva) |
| `dropped_local_network` | descartados por "Internet only" (red local cortada, internet y loopback vivos) |
| `dropped_block` | descartados por los campos de bloqueo (cortafuegos) |
| `dropped_link_outage` | descartados durante un corte de flapping |
| `dropped_rate_limit` | descartados por un búfer de límite de velocidad lleno |
| `dropped_at_stop` | paquetes en cola descartados al detenerse la sesión |
| `dropped_send_failed` | el controlador se negó a reinyectarlos |
| `connections_reset` | conexiones realmente cortadas |
| `connections_refused` | conexiones bloqueadas que se rechazaron en lugar de ignorarse (`--block-reject`) |
| `rst_sent` | paquetes RST que llegaron a la pila |
| `bytes_in` / `bytes_out` | bytes entregados, todo el tráfico capturado |
| `bytes_in_total` / `bytes_out_total` | bytes capturados, antes del deterioro |
| `delivered_in_scope_bytes_down` / `delivered_in_scope_bytes_up` | bytes entregados, solo el tráfico del objetivo |
| `queue_len` / `queue_peak` | paquetes esperando en la cola de retardo, ahora y en el pico |
| `driver_wait_peak_ms` | lo máximo que el controlador hizo esperar a un paquete antes de que la herramienta lo viera, contado una vez que la herramienta está leyendo (los paquetes capturados mientras START aún se estaba preparando quedan fuera) |

Los tres últimos contadores de descartes (`dropped_overflow`, `dropped_at_stop`,
`dropped_send_failed`) son pérdidas de la **propia herramienta** y no un deterioro que se pidió, y por
eso se cuentan aparte.

### Columnas del CSV de conexiones

Las mismas filas que la tabla, pero **los encabezados no son las etiquetas de la tabla**: escriben
completo lo que la tabla abrevia:

| columna CSV | columna de la tabla |
|---|---|
| `process`, `pid`, `proto`, `remote_ip`, `remote_port`, `local_port`, `packets` | igual, sin abreviar |
| `impaired` | `impaired?` (`yes` / `no`) |
| `dropped` | `dropped` |
| `delivered_down_bytes`, `delivered_up_bytes`, `delivered_total_bytes` | `down`, `up`, `total` - **aquí siempre son bytes en bruto**, nunca la unidad que eligió la pantalla |
| `captured_down_bytes`, `captured_up_bytes`, `captured_total_bytes` | `down seen`, `up seen` (más su total) |
| `avg_bytes` | `avg[B]` |
| `duration_s`, `idle_s` | `time[s]`, `idle[s]` |

## Formato del archivo de escenario

Un escenario es una línea de tiempo: una lista de pasos, cada uno con un tiempo en segundos y lo que
hay que hacer en ese momento. El archivo es JSON, ya sea un objeto o una lista simple de pasos:

```json
{
  "loop": true,
  "steps": [
    { "at": 0,  "settings": { "latency": 20, "jitter": 15, "loss": 1, "down": 1024, "up": 256 } },
    { "at": 20, "settings": { "loss": 3, "down": 512 } },
    { "at": 45, "action": "reset_tcp", "duration": 5 },
    { "at": 60, "settings": { "loss": 0, "flap_period": 0 } }
  ]
}
```

**Nivel de archivo**

| clave | significado |
|---|---|
| `steps` | obligatoria: la lista de pasos. Un simple `[ ... ]` en el nivel superior también funciona, y significa `loop: false`. |
| `loop` | opcional, por defecto `false`. Repite la línea de tiempo sin fin, reiniciándose tras el `at` del ÚLTIMO paso. Los ajustes y la acción del último paso se aplican justo antes de cada reinicio, de modo que en un bucle dura solo un instante: para mantener una fase final, añada un paso posterior. |

**"Apply changes" mientras se ejecuta un escenario**: se aplica de inmediato, y cada paso posterior se
construye sobre él en lugar de sobre los ajustes que START dio a la sesión. Un ajuste que ningún paso
toca (el proceso objetivo, la selección del destino) conserva su nuevo valor hasta el final. Un ajuste
que los pasos definen conserva el nuevo valor solo hasta el paso siguiente, que restablece el valor
del escenario.

**Nivel de paso**: un paso necesita `settings`, `action` o ambos. Uno que no tenga ninguno es un
error, no una pausa.

| clave | significado |
|---|---|
| `at` | obligatoria: segundos desde el inicio de la sesión (`>= 0`). Los pasos se ordenan por ella, así que su orden en el archivo no importa. |
| `settings` | un objeto de ajustes **parcial**. **Acumulativo**: cada paso modifica el estado que dejaron los anteriores, de modo que un valor se mantiene hasta que algún paso posterior lo cambia de nuevo. |
| `action` | `reset_tcp`: corta las conexiones TCP dentro del alcance en ese momento. **Es la única acción.** La grafía `reset_now`, anterior a la 1.3, se ha eliminado, así que un archivo que aún la use no se carga y muestra un mensaje que nombra el paso. |
| `duration` | segundos que el reset mantiene caídas las conexiones (por defecto `3`), más de 0 y como máximo 3600. Solo es válido junto con una `action`. |

**Qué nombres van en `settings`**: cualquier ajuste que tenga la herramienta, con el **mismo nombre que
en el archivo de configuración** (es decir, su indicador de línea de comandos con los guiones
convertidos en guiones bajos): `loss`, `latency`, `jitter`, `down`, `up`, `buffer`, `spike_prob`,
`flap_period`, `dst_ip`, `block_port`, `target`, `rate_schedule`, `max_size`, `nat_timeout`,
`rst_prob`, `lan_mode`, `internet_only` y el resto. Ejecute `--print-config` para volcar el conjunto
completo de nombres con sus valores actuales. Un paso no puede cambiar `filter`, `duration`,
`narrow_filter`, `row_limit` ni `seed`: una sesión toma los tres primeros y `seed` solo en START, y
solo las tablas de la ventana leen `row_limit`, nunca el motor. Un paso que defina uno de ellos no
cambia nada: el archivo se carga igualmente y lo dice.

**Todo se valida al cargar el archivo, y un error se identifica por sí mismo.** Un ajuste
desconocido, una acción desconocida, una clave desconocida, un `duration` que no es un número, un paso
que no hace nada, una lista de pasos vacía o de más de **1000** pasos: cada uno falla con un mensaje
que señala el número de paso. Esto importa más de lo que parece: una clave mal escrita solía ser
**silenciosa**, de modo que `"duraton"` dejaba tranquilamente el reset en su valor por defecto de
3 segundos y `"lop"` desactivaba tranquilamente el bucle, y en ambos casos la herramienta parecía
ignorar el archivo.

Los pasos los aplica un temporizador que marca **cada 0,1 s**, así que los tiempos inferiores al
segundo se respetan con ese margen aproximado. `--dry-run` valida un `--scenario` sin tocar el
controlador, lo que lo convierte en una comprobación barata en un pipeline.

### Los escenarios que vienen en `scenarios/`

Todos se repiten en bucle salvo `upload-drop-midway.json`, así que se puede iniciar uno y dejarlo
funcionando.

| archivo | qué reproduce |
|---|---|
| `cafe-wifi.json` | Una cafetería que se llena a lo largo de 85 s: un enlace decente se degrada hasta ~240 ms de ping, 6 % de pérdida y 2 Mbit/s, con la conexión cortándose por completo cada 12 s en el peor momento, y luego se recupera. |
| `mobile-lte-to-3g.json` | Un teléfono que sale de la cobertura LTE: de 33 Mbit/s de bajada a los 0,8 de 3G, luego una **caída total con un TCP reset** a los 60 s, después una recuperación parcial y de vuelta a LTE. Sirve para probar qué hace la aplicación cuando la red muere en mitad de una petición. |
| `congested-vpn.json` | Una VPN cuya **subida** se desploma mientras la bajada sigue bien (de 512 a 160 KB/s), con picos de latencia, una MTU de 1400 y restablecimientos ocasionales. |
| `failing-dns.json` | Dirigido **solo al puerto 53** (DNS: para dejar en paz el DNS sobre TCP, ponga el Filter en "UDP only" antes de START): la resolución de nombres se degrada hasta 60 % de pérdida y 1,5 s de ping, se queda **100 % muerta durante 13 s** y luego vuelve. Todo lo demás de la máquina sigue funcionando, y eso es lo que lo convierte en una prueba de DNS y no de una caída. |
| `overloaded-game-server.json` | Un servidor que se hunde bajo la carga: ping, jitter, pérdida y duplicación suben a la vez, con picos de latencia de hasta 800 ms en el 45 % de los paquetes. |
| `same-loss-in-runs.json` | La misma pérdida del 5 % durante toda la ejecución, llegando de cuatro maneras distintas: repartida uniformemente, y luego en tandas de 5, 15 y 40 paquetes. Nada más cambia, así que lo que se rompe es la FORMA de la pérdida y no cuánta hay. Sirve para averiguar si funciona el camino de reconexión. |
| `upload-drop-midway.json` | **No se repite en bucle**, es de una sola vez: una subida que empieza sana, se degrada, se **corta a cero a mitad de la transferencia** con un TCP reset y luego se recupera parcialmente. Para probar subidas reanudables y barras de progreso que mienten. |
| `blocked-endpoint.json` | Un backend (`203.0.113.0/24`) queda **bloqueado** a los 20 s mientras todo lo demás sigue funcionando, y luego se desbloquea. Para probar timeouts, reintentos y alternativas ante una sola dependencia. |

## Recetas de CI/CD

### 1. Degradación del enlace en segundo plano durante pruebas E2E (GitHub Actions, Windows)

Las pruebas se ejecutan con 300 ms de retardo y 5 % de pérdida. El modelador se detiene solo a los
120 s, de modo que ningún paso "atascado" deja una red rota en el agente.

```yaml
- name: Start the network shaper (background, self-stopping)
  shell: pwsh
  run: |
    $p = Start-Process -FilePath dist\BeanNetworkTester\BeanNetworkTester.exe `
      -ArgumentList '--latency','300','--loss','5','--duration','120',
                    '--dst-port','443','--fail-on-no-traffic',
                    '--format','json','--log-file','shaper.log' `
      -RedirectStandardOutput shaper.ndjson -PassThru
    "SHAPER_PID=$($p.Id)" >> $env:GITHUB_ENV

- name: Run the E2E suite under bad network
  run: npm run test:e2e

- name: Stop the shaper and check it actually impaired something
  if: always()
  shell: pwsh
  run: |
    Stop-Process -Id $env:SHAPER_PID -ErrorAction SilentlyContinue
    Get-Content shaper.ndjson | Select-Object -Last 1
```

> **Nota:** ejecute el proceso en segundo plano con `--duration`: es la red de seguridad. Aunque el
> paso "Stop" no llegue a ejecutarse (cancelación del job, timeout), la sesión se cierra sola, el
> controlador se libera y el agente recupera su red normal.

### 2. Validación de la configuración en pre-commit / PR (sin controlador, sin administrador)

```bat
BeanNetworkTester.exe --dry-run --config profiles/bad-3g.json
```
Código `0` = el archivo es válido. `3` = hay un error (con un mensaje legible en stderr). Un ajuste
mal escrito cuenta como error y dice de qué clave se trata: antes se descartaba en silencio, de modo
que la comprobación pasaba y la ejecución salía después sin ese ajuste.

`--dry-run` comprueba los **ajustes**, no la máquina: nunca pregunta por los derechos de administrador
ni por el controlador, así que responde `0` en un agente de compilación que en realidad no podría
ejecutar una captura. Es deliberado: validar una configuración en un sitio y ejecutarla en otro es lo
normal. Cuando se quieran responder ambas mitades, ejecute la pareja:

```bat
BeanNetworkTester.exe --doctor && BeanNetworkTester.exe --dry-run --config profiles/bad-3g.json
```

### 3. Una ejecución corta y repetible con un artefacto

```bat
BeanNetworkTester.exe --preset presets.3g --seed 42 --duration 60 ^
  --repro-out repro.json --format json --fail-on-no-traffic > run.ndjson
```
Los artefactos (`run.ndjson`, `repro.json`) bastan para recrear las condiciones 1:1. `repro.json`
contiene un `cli_command` listo.

### 4. Limpieza del entorno del agente

```bat
BeanNetworkTester.exe --doctor
BeanNetworkTester.exe --cleanup-driver
```

## Cómo crear un .exe

En Windows:

```bat
pip install pyinstaller pydivert psutil
pyinstaller --noconfirm BeanNetworkTester.spec
```

Resultado: **`dist\BeanNetworkTester\BeanNetworkTester.exe`** (un directorio con el exe, el
controlador WinDivert, las traducciones y el icono). Ese único archivo ejecuta **tanto la GUI como la
CLI**.

Tres decisiones de compilación deliberadas (no las cambie sin necesidad: cada una corrige un error
real):

- **subsistema de consola** (no `--noconsole`): de lo contrario, el exe no tiene `stdout`/`stderr`, y
  `cmd.exe` y PowerShell **no esperan** a un proceso de GUI: CI no vería ni la salida ni el código de
  salida. Al iniciar la GUI, el programa se desvincula por sí mismo de la consola, así que un doble
  clic no deja ninguna ventana negra.
- **onedir** (no `--onefile`): `pydivert` incluye `WinDivert64.sys`, y onefile lo descomprimía en
  `%TEMP%\_MEIxxxx`. El kernel mantiene abierto un identificador sobre el `.sys` cargado, así que el
  directorio **no se podía borrar** hasta reiniciar. En la compilación en directorio, el controlador
  está junto al exe, en una ruta estable.
- **`asInvoker`** (no `--uac-admin`): `requireAdministrator` siempre crea un proceso **nuevo** al
  elevar, con lo que se pierden las tuberías y el código de salida de quien llama. Ahora la propia GUI
  pide la elevación, y la CLI termina con el código `7` y un mensaje claro cuando faltan los derechos
  (`--simulate` no los necesita).

El icono se puede regenerar con un script de Pillow (`pip install pillow`), pero Pillow no hace falta
para el funcionamiento normal.

## Trampas habituales (leer antes de abrir un informe de error)

- **`--duration` es una red de seguridad, no solo una comodidad.** Sin él, una sesión dura hasta
  `Ctrl+C` / STOP. En CI pase **siempre** `--duration`. La única excepción es un escenario con línea
  de tiempo: `--scenario` con un archivo que no se repite en bucle y tiene más de un paso ahora
  termina la ejecución cuando termina el escenario, y lo dice al principio. Un escenario en bucle o
  de un solo paso no tiene un final en el que detenerse, así que avisa y sigue hasta que se lo
  detenga.
- **Cerrar la ventana de la consola detiene una ejecución limpiamente, cerrar sesión no.** Cerrar la
  ventana de la consola termina la ejecución igual que Ctrl+Break: la captura se detiene, se imprime
  el resumen, se escriben el informe de `--repro-out` y el `--log-file` si se pidieron, se descarga el
  controlador WinDivert, el registro dice `Terminated (console window closed).` y el código de salida
  es `143`. Windows espera solo unos 5 segundos para esta limpieza. Cerrar sesión o apagar termina el
  programa de inmediato. Windows sigue cerrando su captura, así que ningún tráfico queda deteriorado,
  pero tras cerrar sesión el controlador puede quedar cargado hasta `--cleanup-driver` o un reinicio.
- **Sin tráfico = una ejecución en verde.** Si el filtro no captura ni un solo paquete, el programa
  funciona correctamente y termina con el código `0`. ¿Se quiere que eso sea un error? Use
  `--fail-on-no-traffic`.
- **El filtro de tráfico y la duración surten efecto solo desde START** (como en la GUI): "Apply
  changes" no los toca.
- **Tras STOP se descartan los paquetes que esperan en la cola de retardo.** Con `--latency 5000`
  pueden ser bastantes paquetes de golpe: no es una fuga, es el final de la sesión.
- **El límite de velocidad tiene un búfer (`--buffer`, por defecto 1000 ms).** Con una carga ofrecida
  superior al límite, una vez que el búfer se llena el exceso se contabiliza como "Rate-limit drop"
  (un contador aparte): es el comportamiento de un enlace atascado, no un error. Subir el límite a
  mitad de una sesión surte efecto solo después de que el búfer se vacíe (hasta ~`--buffer` ms). ¿Se
  quiere el antiguo búfer ilimitado (paquetes en lugar de descartes, a costa de un retardo creciente)?
  Defina `--buffer 0`.
- **`--dst-port "!53"` también captura el tráfico sin puerto** (p. ej. ICMP): un paquete sin puerto
  "no es el puerto 53".
- **Un nombre de proceso simple es una subcadena**: `--target chrome` también captura
  `chromedriver.exe`. Con precisión: `--target "re:^chrome\.exe$"`.
- **Los rangos son inclusivos en ambos extremos** (`80-80` = un puerto), como en nmap/iptables.
- **La CLI está siempre en inglés**, con independencia del idioma de la GUI y del sistema.
- **`-q` es silencioso de verdad**: si todo va bien, no imprime nada. Lea el resultado del código de
  salida (o añada `--format json`).
- **Ejecutar sin administrador** (y sin `--simulate`) termina con el código `7`, no con "silencio".
- **¿El controlador bloqueó un archivo en `%TEMP%`?** Es una reliquia de las antiguas compilaciones
  onefile: `BeanNetworkTester.exe --cleanup-driver` lo libera sin reiniciar el sistema.

## Pruebas

El motor está separado de WinDivert, así que las pruebas se ejecutan en cualquier sistema (no
necesitan ni Windows, ni administrador, ni tkinter). El conjunto se basa en **pytest**:

```bat
pip install --require-hashes -r requirements.txt
pip install -r requirements-dev.txt
python -m pytest tests
```

Cubren todos los mecanismos: pérdida, latencia, jitter, limitación de velocidad por sentido,
corrupción, duplicación, expresiones de filtro (listas, rangos, `!`, `>`, `<`, comodines, `re:`,
CIDR, IPv6), selección de procesos y destinos, descarte de SYN, MTU, flapping, caducidad de NAT,
inyección de RST, picos de latencia, la programación, el registro de conexiones, la repetibilidad
(semilla), los escenarios, el archivo de configuración, el resumen (PL/EN), las traducciones de la
interfaz y la reproducción (semilla efectiva, registro de eventos, informe y comando de CLI). Una
prueba aparte ejecuta también el smoke de la GUI (`smoke_gui.py`, sobre un tkinter simulado), y las
convenciones del repositorio (nombres, ausencia de tkinter en el paquete central, capas permitidas)
están protegidas por pruebas.

El **contrato de la CLI para CI/CD** se protege por separado:
- `tests/test_cli_runtime.py` - códigos de salida (0/1/3/4/5/6/130/143), precisión de `--duration` (no
  "hasta el informe más cercano"), separación de stdout/stderr, NDJSON, `-q`/`-v`, `--dry-run`,
  `--print-config`, `--min-packets`, precedencia de `--duration` sobre el archivo de configuración. Al
  bucle de informes se le inyecta un reloj, de modo que las pruebas de duración se ejecutan en
  microsegundos.
- `tests/test_failsafe.py` - la sesión se detiene sola tras `duration`, un hilo de captura muerto
  provoca un *fail-open* (liberar el controlador = la red vuelve), el `_tick` de la GUI sobrevive a
  una excepción, el hilo de selección de objetivos nunca toca tkinter, cerrar la ventana siempre
  libera el motor.

**GitHub Actions** ejecuta las mismas pruebas en cada push (`.github/workflows/ci.yml`), en una
matriz de Linux + **Windows**: el conjunto de pruebas tras una **barrera de cobertura**, el smoke de
la GUI sobre el tkinter simulado, aserciones de códigos de salida, una comprobación de NDJSON,
`--doctor` y `--license`, y después **una compilación del `.exe` con una prueba de humo del archivo
compilado** (`--version`, `--simulate`, una configuración incorrecta -> código 3) más una
comprobación de que el controlador WinDivert realmente se incluyó junto al exe, con un artefacto
descargable.

<!-- ci-jobs:start -->
Todos los jobs de ese workflow, y qué significa que uno esté en rojo:

| job | qué hace |
|---|---|
| `public-text` | mensajes de commit y la descripción del pull request: en inglés, con guiones simples, sin nada privado de una máquina |
| `lint` | **ruff**. El código muerto, las formas típicas de error, el techo de complejidad y el techo de argumentos hacen fallar la ejecución. La familia de seguridad se informa y nunca bloquea |
| `types` | **mypy** sobre el paquete |
| `semgrep` | el conjunto de reglas por defecto del registro. ERROR, HIGH y CRITICAL hacen fallar la ejecución, el resto se imprime |
| `mutations` | rompe cada comportamiento protegido y demuestra que su prueba se pone en rojo. Un pull request ejecuta las entradas que tocó, la ejecución semanal las hace todas |
| `audit` | **pip-audit** contra el conjunto fijado. Semanal, para preguntar si el mundo se movió bajo versiones que no lo hicieron, y en un pull request que edita un archivo de requisitos, para preguntar si el conjunto se movió. La ejecución semanal abre un issue, y un pull request que fija algo vulnerable simplemente falla |
| `tests` | el conjunto de pruebas, el smoke de la GUI, la comprobación de renderizado con Tk real y las aserciones de la CLI, en Linux y Windows |
| `build` | el ejecutable de Windows, con prueba de humo, con la comprobación del controlador y el análisis del registro de licencias |
| `cron-issue` | abre un issue cuando la ejecución semanal se pone en rojo, sin duplicados según qué jobs fallaron. Un cron es fácil de pasar por alto y nada más lo anuncia. También responde a una ejecución lanzada a mano, que es la única forma de ejercitarlo sin esperar a un lunes en rojo. Nunca se ejecuta en un pull request, y nunca cierra un issue por sí mismo |
<!-- ci-jobs:end -->

**Tres comprobaciones estáticas se ejecutan junto a las pruebas**, solo en Linux, porque leen el
código fuente en lugar de ejecutarlo. **ruff** hace fallar un pull request ante un hallazgo de código
muerto o de forma típica de error (`F` y `B`) e informa de la familia de seguridad (`S`, `ASYNC`)
como anotaciones que nunca bloquean. Dos de sus reglas son techos y no opiniones: `C90` para cuántos
caminos hay a través de una función y `PLR0913` para cuántos argumentos admite, ambos fijados en lo
más ancho que existe hoy, de modo que permanecen en silencio hasta que algo crezca más allá. **mypy**
comprueba los tipos del paquete. **semgrep** analiza con su conjunto de reglas por defecto del
registro, y un hallazgo en ERROR, HIGH o CRITICAL hace fallar la ejecución, mientras que todo lo que
queda por debajo se imprime íntegro. Las versiones de las tres herramientas están fijadas, de modo que
una versión nueva de un linter no puede poner en rojo un pull request que no cambió nada: ruff y mypy
en `requirements-lint.txt`, que CI instala por hashes exactos de archivo, y semgrep en
`requirements-scan.txt`, fijado solo a una versión. Semgrep es el único lugar donde una fijación no
puede prometer una respuesta estable de todos modos, porque descarga sus reglas al ejecutarse.

**Las dependencias se comprueban desde tres lados.** El job `audit` ejecuta pip-audit sobre el
conjunto de ejecución y de compilación tal como está instalado. `review new dependencies`
(`.github/workflows/dependency-review.yml`) hace fallar un pull request que añade una dependencia con
un aviso conocido o con una licencia que el proyecto no puede distribuir. **OSV-Scanner**
(`.github/workflows/osv-scanner.yml`) lee todos los archivos de requisitos fijados contra la base de
datos OSV: en `master` y cada semana informa a la pestaña Security, y en un pull request solo falla
cuando ese pull request incorpora un aviso nuevo.

Hay un paso que merece conocerse porque ninguna prueba unitaria puede hacer su trabajo: una
**comprobación de renderizado de la GUI sobre Tk real** bajo una pantalla virtual, con el mínimo
admitido de 1366x768, **en todos los idiomas**. Construye la ventana real, recorre todas las páginas,
abre la ventana About y hace fallar la compilación cuando algún botón es más estrecho de lo que pide,
es decir, cuando su texto queda recortado. Las etiquetas en polaco son más largas que las inglesas,
así que ahí es donde se rompen las maquetaciones, y ha detectado roturas que eran invisibles en
inglés.

Las versiones se publican mediante un segundo workflow (`.github/workflows/release.yml`) con una
etiqueta `v*`. Comprueba la etiqueta contra `VERSION.txt`, se niega a publicar mientras los registros
de cambios sigan abiertos, compila y prueba el exe, y abre un **borrador** que lleva el SBOM SPDX.
Deliberadamente no publica ningún archivo: la clave de firma vive en una tarjeta de hardware a la que
ningún runner puede llegar, así que el archivo se firma en la máquina del mantenedor
(`tools/sign_release.py`) y se sube desde allí, y un tercer workflow certifica después los bytes que
realmente se distribuyen.

Una versión publicada lleva, por tanto, el zip, el `SHA256SUMS.txt` que este README indica verificar,
el SBOM y el paquete de atestación. Una versión completa lleva un quinto archivo, el instalador
`.msi`. Un candidato a versión no lo lleva, porque Windows Installer ignora el `-rc.1` y trataría a un
candidato y a su versión final como la misma versión.

## Estructura del proyecto

El código se divide en el paquete `beantester/`. Un lanzador delgado `bean_network_tester.py` queda en
la raíz, de modo que todos los comandos existentes (README, informes de reproducción, PyInstaller)
funcionan sin cambios.

```
bean_network_tester.py   lanzador + fachada de compatibilidad (reexporta la API pública)
beantester/              el paquete de la implementación
  core.py                núcleo puro de decisión por paquete (BeanCore)
  damage.py              cuánto dañó una sesión: motivos de descarte, proporciones de pérdida/corrupción
  engine.py              hilos de captura/inyección, estadísticas (BeanEngine)
  connlog.py             el registro de conexiones de la sesión: una fila por flujo, y su tope
  driverwait.py          cuánto esperaron los paquetes en la cola del controlador antes de que la herramienta los recibiera
  matchers.py            expresiones de filtro (lista/rango/!/>/</comodín/re:), compartidas
                         por los campos de proceso, IP y puerto: una única fuente de verdad
  settings.py            modelo de ajustes, archivo de configuración, apply_settings
  scenario.py  presets.py  filters.py  summary.py  repro.py  views.py
  cli.py                 analizador de argumentos, modo CLI y despachador GUI/CLI
  exitcodes.py           CÓDIGOS DE SALIDA: el contrato de CLI/CI-CD (única fuente de verdad)
  clilog.py              salida de la CLI: registro en stderr ([bean]), datos en stdout (texto/NDJSON)
  winenv.py              Windows: administrador, elevación (UAC), desvinculación de la consola, DPI
  driver.py              ciclo de vida del controlador WinDivert + --doctor / --cleanup-driver
  fields.py              REGISTRO DE CAMPOS, única fuente de verdad: tipo, etiqueta, unidad,
                         rango, sección del formulario, ámbito del perfil, indicador de CLI
  validators.py          validación de números y rangos (compartida por GUI, CLI y archivo de configuración)
  portmap.py             tabla de sockets: puerto local -> PID (iphlpapi/ctypes, alternativa psutil),
                         y cada socket con su estado para la pestaña Tools
  adapters.py            adaptadores de red y la ruta de salida (iphlpapi/ctypes), para la pestaña Tools
  proxy.py               el proxy que usan esta cuenta y esta máquina (winhttp/ctypes y el
                         registro), solo lectura, para la pestaña Tools
  tcpreset.py            restablecer una conexión TCP (iphlpapi/ctypes), para el menú de fila de la
                         página Connections
  targeting.py           conjunto vivo de puertos objetivo: árbol de procesos, pide reconstruirse ante un fallo
  target_resolver.py     reconstruye ese conjunto de puertos en su propio hilo, fuera del camino del paquete
  socketwatch.py         puerto local -> PID en vivo a partir de eventos SOCKET de WinDivert (fuente dirigida por eventos)
  jsonfile.py            escritura atómica + cuarentena de archivos de usuario corruptos
  crashlog.py            registrador de fallos: quiet/note/once, cuarentena, informe en segundo plano
  appinfo.py             identidad de la aplicación y lector de versión (una sola fuente: VERSION.txt)
  i18n.py  paths.py  utils.py  processes.py  synthetic.py  legal.py  scenario_runner.py
  nettools/              la lógica detrás de la pestaña Tools, un módulo por herramienta - sin tkinter,
                         así que se prueba sin ventana
  gui/                   la interfaz tkinter
    app.py               composición de la ventana, estado, inicio/parada, estado modificado
    logview.py           el cuadro del registro: su cola, su búfer de líneas y su widget
    form.py              formulario generado a partir de fields.FIELD_DEFS
    form_search.py       emparejar una consulta escrita con el registro de campos (puro)
    scaling.py           DPI, píxeles escalados, geometría de ventana/gráfico/tooltip
    wheel.py             normalización de la rueda del ratón (una función pura)
    scrollable.py        ScrollableFrame + UN despachador global de rueda
    accordion.py         secciones plegables
    ui_state.py          persistencia del estado de la ventana (bean_network_tester_ui.json)
    prefs.py             preferencias de la GUI (idioma, gráfico, registro) guardadas en ui.json
    pages/               registro de páginas: control, stats (3 subpestañas), conns, toolbox (Tools)
    toolbox/             la pestaña Tools: su registro de herramientas y un panel por herramienta
    field_actions.py     rellenar un campo de la página Control desde otro lugar (menús de fila de tablas, pestaña Tools)
    clipboard.py         copiar un texto entero, confirmado releyendo el portapapeles
    links.py             los botones Donate y GitHub: el único código que abre una página web
    configure.py         configurar un widget solo con las opciones que realmente cambian
    panels/              ventanas secundarias: "About", "Settings" y el registro de eventos desacoplado
    widgets/             SortableTree (ordenación, diferencia de filas, Ctrl+C, tope de ancho de columna, menú de fila)
    model_worker.py      reconstruye el modelo de una tabla en un hilo de trabajo (la UI nunca se bloquea)
    windows.py           clase base y registro de ventanas secundarias
    dialogs.py           sustitutos oscuros, dentro de la aplicación, de messagebox/simpledialog
    rates.py             promedio de rendimiento y el pico de cada vista (puro, comprobable)
    scope.py             qué cubren los números en pantalla (un único veredicto puro)
    crash.py             lo que la GUI le dice al registrador de fallos: contexto del informe, rastro
    csv_export.py        las dos exportaciones a CSV y los nombres de columna que escriben
    session_repro.py     con qué se ejecutó la sesión: el informe de reproducción y "Copy CLI command"
    applied.py           con qué compara el formulario "Apply changes" (un auxiliar puro)
    theme.py  chart.py  tooltip.py  profiles.py  icon.py  labels.py
lang/                    traducciones (en, pl, zh)
tests/                   pruebas de pytest
smoke_gui.py             smoke de la GUI sobre un tkinter simulado
BeanNetworkTester.spec   la receta de compilación (onedir, console, asInvoker)
```

## Cómo funciona (en resumen)

El núcleo `BeanCore.decide()` es una función pura que decide el destino de un paquete por orden:
selección de objetivos -> modo LAN -> bloqueo (cortafuegos) -> NAT -> RST -> flapping -> MTU -> SYN -> pérdida -> corrupción ->
retardo/jitter/pico -> límite de rendimiento (un token bucket con un búfer acotado, opcionalmente a
partir de la programación) -> duplicación. El hilo de captura lee los paquetes y ejecuta la decisión.
El hilo de reinyección los envía en el momento elegido. Toda la aleatoriedad pasa por un único
generador (opcionalmente con semilla).

## Notas y limitaciones

- Modifica el tráfico que coincide con el filtro. Para pruebas más acotadas, use "Target process" o
  "Target destination".
- Ping = ICMP: para afectarlo, elija un filtro que incluya ICMP.
- Un límite de velocidad es difícil de ver en el ping (paquetes pequeños): pruébelo con una descarga
  de archivo.
- La captura y la inyección reales de RST solo funcionan en Windows con WinDivert. La lógica está
  confirmada por pruebas que se ejecutan en todas partes.
- Una herramienta para probar sus propias aplicaciones y redes.

### Comportamientos que conviene conocer

- **La programación se repite en bucle**: tras el último paso vuelve al primero (`2:100:0, 2:500:0`
  alterna 2 s a 100 KB/s y 2 s a 500 KB/s, sin fin). Aplicar una programación modificada a mitad de
  sesión reinicia el ciclo desde el primer paso. Aplicar la misma de nuevo, o cambiar cualquier otro
  ajuste, deja el ciclo donde está.
- **La programación tiene prioridad sobre un límite fijo**: cuando el campo "Schedule" no está vacío,
  los valores de "Download/Upload" (KB/s) se ignoran, porque el rendimiento procede de los pasos de la
  programación.
- **La programación es opcional, pero debe ser válida**: un campo vacío = sin programación, mientras
  que una entrada incorrecta (p. ej. `1:100`, `2:abc:0`) se notifica como error: la GUI no inicia la
  sesión y la CLI termina con un mensaje. Nada se omite en silencio.
- **Las expresiones de filtro se validan**: una entrada no válida en el campo de proceso/IP/puerto
  (p. ej. `999.1.1.1`, `2000-1000`, `>chrome`, `re:[`) se notifica como error en lugar de no hacer
  nada en silencio: en la GUI el campo se pone en rojo con el motivo debajo, y la CLI termina con un
  mensaje `error: ...`. La comparación de direcciones no depende de la notación (una forma IPv6 corta
  y una completa son la misma dirección).
- **Los positivos suman, las exclusiones restan**: `80,443,!8080` significa "80 o 443 pero no 8080", y
  `!53` solo significa "todo excepto 53". El orden de los términos no importa. Detalles y casos
  límite: [Sintaxis de filtros](#sintaxis-de-filtros-proceso--ip--puerto).
- **Los rangos son inclusivos en ambos extremos**: `8000-8100` abarca 8000 y 8100 (como en
  nmap/iptables), y `80-80` es exactamente un puerto.
- **IP y puerto en "Target destination" se combinan con AND**: definir ambos campos acota al tráfico
  que cumple **las dos** condiciones a la vez.
- **Un límite de velocidad muy bajo = pérdida real**: con el búfer por defecto (1000 ms), el exceso
  por encima del límite se descarta una vez que el búfer se llena y se contabiliza en la estadística
  **"Rate-limit drop"** (un contador aparte, no "Loss"). Así se comporta un enlace congestionado, de
  modo que la pérdida efectiva puede ser entonces mayor que el porcentaje de "Loss" definido. Solo con
  `--buffer 0` (un búfer sin límite) la cola de la herramienta crece hasta su tope máximo de
  **20 000** paquetes, y entonces el exceso se contabiliza como **"Buffer overflow"**.
- **Un campo Seed vacío = una semilla aleatoria**: el programa sortea igualmente un valor concreto y
  lo muestra en el panel de sesión. En los archivos de configuración el valor `-1` significa
  "aleatorizar", por lo que `-1` no se puede usar como semilla normal (cualquier otro número, incluso
  uno negativo, funciona con normalidad).
- **La selección de procesos incluye los procesos hijo**: un socket pertenece al objetivo si el
  proceso **que lo abrió, o cualquiera de sus ancestros**, coincide. Por eso `chrome.exe` (o el PID de
  la ventana del navegador) también captura su proceso de red, que es el que mantiene todas las
  conexiones. Una exclusión explícita gana: `chrome, !chromedriver` no incluirá `chromedriver` a
  través de un padre.
- **La selección de procesos se rige por eventos de socket, no por un sondeo lento.** WinDivert nos
  entrega un paquete, no un PID, así que asociamos un paquete con su proceso por el **puerto local**.
  En Windows la herramienta observa los eventos de socket del sistema (connect / bind / accept /
  close) a medida que ocurren, de modo que una conexión nueva **o un flujo UDP** de un programa que
  **ya** está dentro del alcance se deteriora desde su mismísimo primer paquete: eso cubre las
  consultas DNS y QUIC, cada una de las cuales toma un puerto nuevo. La excepción es la *primera*
  conexión del programa: hasta que posee al menos un socket no hay nada por lo que reconocerlo, así
  que esa conexión pasa sin tocar. Sin un WinDivert real (la vía de pruebas / simulación) recurre a
  examinar la tabla de sockets varias veces por segundo, donde el primer paquete de cualquier conexión
  completamente nueva puede colarse. En ambos casos la vigilancia se ejecuta en su propio hilo, nunca
  en el que maneja los paquetes, así que nunca puede convertirse en tráfico perdido.
- **Si el programa probado se reinicia, apunte por NOMBRE, no por id de proceso.** Medido: un objetivo
  que sale y vuelve con un id de proceso nuevo se vuelve a detectar solo, y el reinicio cuesta
  exactamente una conexión: la que abre antes de poseer ningún socket. Apuntar a un **id de proceso**
  nunca se recupera, porque ese id nombraba al proceso que terminó: todo lo que ocurre tras el
  reinicio queda intacto. Un programa al que Windows asigne más tarde el mismo número también queda
  intacto: un id de proceso solo significa siempre el proceso que lo tenía cuando se fijó el objetivo.
  Desde la línea de comandos, la ejecución lo dice cuando ocurre y termina indicando qué parte del
  tráfico capturado estuvo realmente dentro del alcance. En la ventana, es la nota roja bajo el campo
  de proceso.
- **Una exclusión por sí sola también abarca todo lo que la herramienta no puede identificar.**
  `!chrome` en el campo de proceso significa "deteriorar todo excepto chrome", y "todo" incluye
  cualquier conexión cuyo proceso propietario no se pudo determinar: procesos protegidos del sistema
  que la herramienta no puede abrir y, con la alternativa de sondeo, los primeros paquetes de un
  socket completamente nuevo.
  **Por eso no use una exclusión para proteger una aplicación.** Si se quiere dejar en paz una
  aplicación, nombre la que SÍ se quiere romper (`--target thatapp`): entonces todo lo que no se
  identifique pasa sin tocar, que es la dirección segura. Esto es el reflejo de `!53` en los puertos,
  más abajo.
- **Una selección que no captura nada no rompe nada**: si ningún proceso que coincida tiene una
  conexión abierta, el tráfico pasa sin tocar. Eso cubre un programa que no se está ejecutando y otro
  que se ejecuta pero está inactivo. Cuando un programa así abre una conexión, la herramienta lo añade
  en milisegundos, de modo que los primeros paquetes de esa conexión pueden pasar sin tocar y el resto
  se deteriora. El programa lo dice explícitamente (una nota roja bajo el campo y una entrada de
  registro), porque "una ejecución en la que nada se rompió" se ve idéntica a "la aplicación aguantó".
- **Un nombre de proceso simple es una subcadena**: `chrome` también captura `chromedriver.exe`. Se
  mantiene a propósito (compatibilidad con configuraciones antiguas). Para mayor precisión, recurra a
  `re:^chrome\.exe$` o a la exclusión `chrome, !chromedriver`.
- **Un objetivo que nombra todos los programas no acota nada**: `*.exe`, `exe` o `*` coinciden con casi
  todos los procesos que tienen una conexión, así que una ejecución así recibe la misma advertencia al
  iniciar que una ejecución sin ningún objetivo.
- **Statistics y Connections muestran TODO el tráfico capturado por defecto**: el que deje pasar el
  filtro "Traffic to modify". La selección (proceso / IP / puerto) decide solo **qué se rompe**, no lo
  que se ve en las tablas y los contadores. Dos interruptores de Settings, en la tarjeta **"Scope"**,
  lo cambian, y no son lo mismo:
  - **"Show only the targeted traffic"** acota los contadores, el gráfico de rendimiento, la tabla de
    Connections y el CSV de conexiones a lo que seleccionó su objetivo. Cambia lo que VE, nunca lo que
    se captura, nunca lo que se deteriora, y se puede alternar en cualquier momento.
  - **"Capture only the targeted traffic"** acota la *propia captura*: el controlador deja de entregar
    cualquier cosa que no sea el tráfico de su destino, así que las pestañas cubren ese tráfico porque
    no hay nada más que cubrir. Se fija al iniciar la sesión, y solo funciona para un destino que el
    lenguaje de filtros del controlador pueda expresar: una dirección simple, una lista, un rango o un
    CIDR. Un comodín, un patrón `re:` o apuntar solo a un proceso no se pueden trasladar al
    controlador, y entonces la opción no hace nada. La tarjeta Scope indica cuál de las dos se obtiene
    **antes** de pulsar START, el registro lo repite al iniciar, y la fila **"Capture"** del panel
    Session lo registra para la ejecución.

  Cualquiera que esté activada, **la nota sobre los contadores y sobre la tabla de Connections dice
  qué cubren realmente esas cifras**, incluido el caso en que la captura está acotada *y* hay un
  objetivo de proceso definido: la herramienta captura entonces el tráfico de su destino de todos los
  procesos y deteriora la parte de uno solo, así que los contadores cubren más que el deterioro.
  **Tres contadores se mantienen sobre todo el tráfico incluso con "Show only" activado**: "Queue
  overflow", "Dropped at stop" y "Send failed" cuentan paquetes que perdió *esta herramienta*,
  incluido el tráfico que nunca se seleccionó, y ocultarlos ocultaría el daño propio de la
  herramienta. El CSV de estadísticas tampoco respeta el interruptor "Show only": es un registro en el
  que se añaden filas, así que lleva ambos totales en columnas separadas, pero sí registra "Capture
  only" en cada fila en `capture_narrowed`, porque ese cambia lo que se contó en absoluto. El informe
  de reproducción y `--format json` llevan siempre ambos números.
- **El límite de velocidad da forma al PROMEDIO**: el token bucket deja pasar ráfagas cortas, de modo
  que el "Download/Upload peak" (promediado en una ventana de 1 s) puede ser algo superior al límite
  definido. Los duplicados cuentan para el límite (la segunda copia también viaja por el enlace).
- **La ventana tiene un tamaño máximo y no se puede maximizar**: la maquetación (dos columnas + la
  barra del registro) deja de tener sentido estirada a 4K, así que el tamaño tiene un tope y se ha
  quitado el botón de maximizar.
- **La duración cuenta desde START**: cambiar el campo a mitad de sesión no hace nada (igual que el
  filtro de tráfico). Una vez alcanzado el límite, el programa simplemente hace STOP y deja los
  resultados en pantalla.
- **STOP descarta los paquetes que esperan en la cola de retardo**: el final de una sesión es
  inmediato. Con una `latency` grande esto se nota como un "hueco" puntual. No es un error.
- **Un fallo a mitad de sesión siempre termina con la red restaurada**: si el hilo de captura o el de
  inyección muere, o deja de avanzar durante 10 segundos, el motor hace STOP por sí mismo y libera el
  controlador (*fail-open*), en lugar de mantener abierto un identificador al que nadie llega (esto
  era un camino real hacia "el usuario se queda de repente sin internet"). El motivo va al registro y
  al registro de eventos. Un hilo que sigue atascado tras STOP se deja atrás en lugar de esperarlo, y
  el siguiente START lo dice en el registro.
- **Cerrar el programa libera el controlador WinDivert**: no tras cada sesión (reiniciar una sesión
  debe ser instantáneo), sino **una vez, al salir**. Mientras el controlador está cargado, el kernel
  mantiene abierto el `WinDivert64.sys` que está junto al exe, y entonces **el directorio del programa
  no se puede eliminar, aunque parezca vacío** (Windows deja borrar un archivo con un identificador
  abierto: desaparece de la lista, pero queda en *pending delete* y bloquea el directorio). Si algo
  queda atrás, el rescate sin reiniciar es `BeanNetworkTester.exe --cleanup-driver` (o `sc stop
  WinDivert` + `sc delete WinDivert`). Al salir, el programa toca solo el servicio `WinDivert` que
  carga, y lo deja cargado mientras otra copia de este programa lo esté usando. `--cleanup-driver` también detiene
  `WinDivert1.4` y `WinDivert1.1`, que instalan otros programas.
- **"Duration" y "Traffic to modify" se tienen en cuenta solo en START**: por eso durante una sesión
  ambos están **bloqueados** (un campo editable que no hace nada es peor que uno atenuado).

## Cómo contribuir

Las contribuciones son bienvenidas. [CONTRIBUTING.md](CONTRIBUTING.md) explica cómo preparar las
pruebas y las convenciones que sigue el proyecto. Lea también el
[Código de conducta](CODE_OF_CONDUCT.md). Los informes de errores y las solicitudes de funciones
pasan por las plantillas de issues, y los problemas de seguridad se tratan en privado mediante la
[política de seguridad](SECURITY.md).

## Apoyar el proyecto

El proyecto lo desarrolla **DonislawDev** y es gratuito. Si la herramienta ahorra tiempo y se desea
que aparezcan más funciones, se puede apoyar su desarrollo **de forma voluntaria**:

**https://donislawdev.com/support/**

El apoyo es totalmente opcional: toda la funcionalidad funciona sin él. En el programa, el botón
**Donate** lleva allí (el encabezado de la ventana y la ventana About). El botón **GitHub** que hay
junto a él abre la página de este proyecto.

## Autor

**DonislawDev** - https://donislawdev.com/

Bean Network Tester está creado con un flujo de trabajo asistido por IA.

## Licencia

Bean Network Tester es **software libre y de código abierto**, con licencia **GNU General Public
License, versión 3 (GPLv3)**: véase el archivo [LICENSE](LICENSE).

En resumen: es libre de usarlo para cualquier fin (privado o comercial), de estudiar cómo funciona y
modificarlo, y de redistribuir copias, incluidas las modificadas, siempre que se transmita el
programa bajo los mismos términos de la GPLv3 y se ponga a disposición el código fuente
correspondiente. El programa se proporciona "TAL CUAL", sin garantía y sin responsabilidad por parte
del autor. El autor es **DonislawDev**.

### Marcas comerciales y las cifras de los preajustes

Ookla, Speedtest, Starlink, HughesNet y Viasat son marcas comerciales de sus respectivos titulares.
Se nombran en este proyecto por una única razón: indicar de **quién son las mediciones publicadas**
de las que proceden las cifras de un preajuste. Bean Network Tester no está afiliado a ninguno de
ellos, ni cuenta con su respaldo o patrocinio, y aquí no se redistribuye ninguno de sus datos: solo
cifras individuales, citadas con su fuente, como lo hace cualquier documento técnico.

### Lo que se crea con él es suyo

**La GPL cubre el programa, no lo que este produce.** Los archivos de escenario que se escriban, los
perfiles y archivos de configuración guardados, los informes de reproducción, los CSV exportados, los
archivos de registro y las capturas de pantalla son obra propia. Usar Bean Network Tester no los
somete a la GPL ni obliga a publicar nada. Manténgalos en privado, distribúyalos con un producto de
código cerrado, véndalos: es decisión suya.

Lo único que hay que mantener aparte: los escenarios de ejemplo que vienen **con** el programa, en el
directorio `scenarios/`, forman parte del proyecto y son GPLv3 como el resto. Un escenario escrito por
uno mismo no lo es, aunque se haya partido de uno de ellos y se hayan cambiado los números.

## Componentes de terceros

El programa usa bibliotecas de otros autores, con sus propias licencias, entre ellas
**[WinDivert](https://www.reqrypt.org/windivert.html)** y
**[PyDivert](https://github.com/ffalcinelli/pydivert)** con **LGPLv3**,
**[psutil](https://github.com/giampaolo/psutil)** (BSD), **[CPython](https://www.python.org/)** (PSF),
**[Tcl/Tk](https://www.tcl-lang.org/)** y el cargador de arranque de
**[PyInstaller](https://pyinstaller.org/)**. La lista completa, las versiones y las direcciones del
código fuente están en [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md), y los textos completos de
las licencias están en el directorio `licenses/`. Desde el propio programa: `--license` (CLI) o el
botón **About** de la interfaz.

Las bibliotecas LGPL se pueden sustituir por versiones propias compatibles con la interfaz, y las dos
se sustituyen de manera distinta. **WinDivert** es una DLL y un controlador que se cargan desde el
disco en tiempo de ejecución, así que se cambian los archivos en `_internal\pydivert\windivert_dll\`,
y por eso el programa se compila como **onedir** y no como un solo archivo. **PyDivert** es Python
puro y está compilado dentro del .exe, así que se sustituye volviendo a compilar el programa contra
su versión, o ejecutándolo desde el código fuente. Dejar una copia modificada junto al .exe no
funciona, y [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md) lo dice en lugar de dejar que se
descubra por cuenta propia. La GPLv3 es compatible con las licencias de estos componentes, y nada en
la licencia del proyecto restringe los derechos que se derivan de ellas.

## Privacidad: sin telemetría

Bean Network Tester **no envía nada por su cuenta**. No tiene telemetría, ni comprobación de
actualizaciones, ni servicios externos. La herramienta captura tráfico de red en su equipo, y esos
datos **nunca salen de él**. Solo salen dos cosas, y solo cuando se piden: una página abierta en el
navegador (la página de apoyo o la página del proyecto en GitHub), cuando se hace clic por cuenta
propia en el botón correspondiente, y las solicitudes de eco de la herramienta **Ping** de la
pestaña Tools, que van solo a la dirección que se escribe, de Start a Stop. Si se escribe un nombre
en lugar de una dirección, Windows lo busca primero, como para cualquier programa.

## Una nota sobre SmartScreen y el antivirus

**Desde la 0.5.0 el .exe está firmado**, con un certificado cuya clave privada vive en una tarjeta de
hardware que nunca sale del escritorio del mantenedor, así que Windows nombra al editor en lugar de
decir "Editor desconocido". Conviene tener claro lo que eso aporta y lo que no: un certificado nuevo
aún no tiene reputación en SmartScreen, por lo que todavía puede aparecer una advertencia durante un
tiempo, y algunos antivirus pueden seguir dando una falsa alarma sobre un programa que pide derechos
de administrador y carga un controlador de red. Lo que cambia es que la advertencia ahora dice quién
lo firmó. El **propio controlador WinDivert está firmado digitalmente por su autor**. Aún se puede
comparar la suma de comprobación SHA-256 de la versión (`SHA256SUMS.txt`) para confirmar que el
archivo llegó sin cambios.

**También se puede comprobar lo que contiene la descarga, no solo que no ha cambiado.** Cada archivo
de versión lleva una declaración firmada que enumera todo lo que hay dentro, hecha por el propio
workflow de este repositorio sobre los bytes exactos que se descargaron:

```bash
gh attestation verify BeanNetworkTester-v0.5.0-windows-x64.zip -R donislawdev/BeanNetworkTester --predicate-type https://spdx.dev/Document/v2.3
```

Una suma de comprobación demuestra que el archivo coincide con lo que dice la página de la versión.
Esto demuestra que la lista de materiales que lo acompaña describe esos mismos bytes, y que la
declaración la hizo un workflow de este repositorio y no quien le entregó el archivo.

`--predicate-type` no es opcional. Sin él, `gh` busca una declaración de procedencia de compilación y
responde `HTTP 404`, porque el archivo que se descarga se **firmó en la máquina del mantenedor**, no
se compiló en un runner: la clave de firma está en una tarjeta a la que ningún runner puede llegar. La
procedencia se atestigua para la compilación sin firmar dentro del workflow. Lo que viaja con la
versión es la lista de materiales sobre el archivo firmado.

Ese comando pregunta a GitHub qué atestaciones existen. La prueba también se distribuye **como
archivo**, `BeanNetworkTester-vX.Y.Z.sigstore.json`, de modo que se puede comprobar el archivo
comprimido con una evidencia que viajó con él:

```bash
gh attestation verify BeanNetworkTester-v0.5.0-windows-x64.zip --bundle BeanNetworkTester-v0.5.0.sigstore.json --repo donislawdev/BeanNetworkTester --predicate-type https://spdx.dev/Document/v2.3
```

Hacen falta ambos indicadores adicionales y ninguno es decoración. `--repo` nombra el repositorio con
el que tiene que coincidir la identidad de la firma. `--predicate-type` está ahí porque este paquete
es la atestación del **SBOM**, y `gh` busca una de procedencia de compilación a menos que se indique
otra cosa: sin él se obtiene "no attestations found with predicate type", que es la herramienta siendo
precisa y no estando rota. Cuando el archivo es bueno, no imprime nada y termina con 0. Si se cambia
un solo byte, termina con 1.

Son tres declaraciones, y conviene saber que responden a preguntas distintas. La **firma** dice quién
respalda el archivo. El **paquete de arriba** vincula este archivo exacto con su lista de materiales,
y se hace después de firmar, sobre los bytes que se descargaron. La **procedencia de compilación**
dice qué commit y qué workflow produjeron la compilación que luego se firmó: describe
necesariamente la compilación sin firmar, porque firmar cambia los bytes, y vive en el almacén de
atestaciones de este repositorio y no en la descarga.

### Qué hay dentro de la descarga y cómo comprobarlo

Cada versión lleva un **SBOM**: una lista, en el formato estándar SPDX, de cada componente de
terceros de la compilación con su versión, su licencia y el lugar donde está su código fuente. Es la
misma lista que imprime `BeanNetworkTester.exe --license`, en una forma que una herramienta puede
leer.

El SBOM está **firmado contra el archivo que describe**, de modo que ambos no se pueden separar:

```bash
gh attestation verify BeanNetworkTester-vX.Y.Z-windows-x64.zip --repo donislawdev/BeanNetworkTester --predicate-type https://spdx.dev/Document/v2.3
```

Una suma de comprobación dice que el archivo llegó sin cambios. La atestación dice que *esta* lista
de materiales pertenece a *este* archivo, y que la declaración la hizo el workflow de publicación de
este repositorio. Si se omite `--predicate-type`, `gh` busca en su lugar una declaración de
procedencia de compilación y responde `HTTP 404`.
