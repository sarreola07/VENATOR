// Spanish for the product site, neutral Latin American.
//
// Each entry's English is the comment above it, so this file reads as the
// review table: change the Spanish on the right, never the key on the left.
// The keys are the data-i18n / data-i18n-attr names in index.html and
// how-it-works.html; tests/test_site_i18n.py checks that every key used on a
// page is here and every key here is used. Hardware names (Pixhawk 6X, OAK-D
// Pro, Holybro M10) and units stay as they are in the markup. The labels drawn
// inside the diagrams are still English: see docs/BRAND.md.
//
// " " is a non-breaking space, used where the English uses &nbsp; so a
// number never ends a line without its unit.
window.VENATOR_ES = {

  // ---- shared -----------------------------------------------------------
  // EN: The Venator aircraft: a Holybro X500 V2 quadcopter with four carbon arms, an OAK-D Pro camera on the nose bracket and twin landing skids
  "shared.social_alt": "La aeronave Venator: un cuadricóptero Holybro X500 V2 con cuatro brazos de carbono, una cámara OAK-D Pro en el soporte de la nariz y dos patines de aterrizaje",
  // EN: Venator, autonomous flight systems
  "nav.lockup": "Venator, sistemas de vuelo autónomo",
  // EN: Primary
  "nav.primary": "Principal",
  // EN: Product
  "nav.product": "Producto",
  // EN: How it works
  "nav.how": "Cómo funciona",
  // EN: Timeline
  "nav.timeline": "Cronología",
  // EN: MIT licensed. Built by Sergio Arreola.
  "foot.lic": "Licencia MIT. Hecho por Sergio Arreola.",

  // ---- index.html: head ---------------------------------------------------
  // EN: Venator: Autonomous Flight Systems
  "index.title": "Venator: Sistemas de vuelo autónomo",
  // EN: Fence an area. Find who's in it. Come home. An autonomous safety drone with onboard AI that runs on its own radio link. No internet. No cell service.
  "index.desc": "Cerca un área. Encuentra a quien esté ahí. Vuelve a casa. Un dron de seguridad autónomo con IA a bordo que funciona con su propio enlace de radio. Sin internet. Sin señal celular.",

  // ---- index.html: hero ---------------------------------------------------
  // EN: Autonomy
  "hero.kicker": "Autonomía",
  // EN: Fence an area.
  "hero.beat1": "Cerca un área.",
  // EN: Find who's in it.
  "hero.beat2": "Encuentra a quien esté ahí.",
  // EN: Come home.
  "hero.beat3": "Vuelve a casa.",
  // EN: An autonomous safety drone with onboard AI. It finds the people it's sent for and ignores everything else. It runs on its own long-range radio, so it works where networks don't.
  "hero.p": "Un dron de seguridad autónomo con IA a bordo. Encuentra a las personas que se le indican e ignora todo lo demás. Funciona con su propia radio de largo alcance, así que opera donde no hay redes.",
  // EN: See how it works
  "hero.cta": "Ver cómo funciona",
  // EN: The Venator aircraft: a Holybro X500 V2 quadcopter with four carbon arms carrying 2216 motors and ten inch propellers, an OAK-D Pro camera on the nose bracket, the GPS mast at the tail and twin landing skids
  "hero.cine_alt": "La aeronave Venator: un cuadricóptero Holybro X500 V2 con cuatro brazos de carbono que llevan motores 2216 y hélices de diez pulgadas, una cámara OAK-D Pro en el soporte de la nariz, el mástil del GPS en la cola y dos patines de aterrizaje",

  // ---- index.html: numbers band -------------------------------------------
  // EN: Long-range radio
  "nums.radio": "Radio de largo alcance",
  // EN: LoRa, proven on real hardware
  "nums.radio_note": "LoRa, probada en hardware real",
  // EN: Networks required
  "nums.networks": "Redes necesarias",
  // EN: No internet or cell service
  "nums.networks_note": "Sin internet ni señal celular",
  // EN: Hover time
  "nums.hover": "Tiempo de vuelo",
  // EN: Holybro spec, stock frame
  "nums.hover_note": "Especificación Holybro, estructura de serie",
  // EN: Payload
  "nums.payload": "Carga útil",
  // EN: Holybro spec, stock frame
  "nums.payload_note": "Especificación Holybro, estructura de serie",

  // ---- index.html: missions -----------------------------------------------
  // EN: Mission
  "missions.lab": "Misión",
  // EN: Built to keep people safe
  "missions.h2": "Hecho para cuidar a las personas",
  // EN: Three real problems at UTSA. One autonomous drone.
  "missions.cap": "Tres problemas reales en UTSA. Un dron autónomo.",
  // EN: No app. No signal. Still connected.
  "m1.title": "Sin app. Sin señal. Siempre conectado.",
  // EN: Live video and text on any phone.
  "m1.t": "Video en vivo y mensajes en cualquier teléfono.",
  // EN: The drone hosts its own Wi-Fi and server. Any phone can connect and watch live video in a web browser, with no app to install. It also sends text messages over its long-range radio to every station in range, like a cell network without the towers.
  "m1.p": "El dron aloja su propio Wi-Fi y su propio servidor. Cualquier teléfono puede conectarse y ver video en vivo en el navegador, sin instalar ninguna app. También envía mensajes de texto por su radio de largo alcance a todas las estaciones al alcance, como una red celular sin torres.",
  // EN: It finds the worker who needs help.
  "m2.title": "Encuentra al trabajador que necesita ayuda.",
  // EN: Watches the crew, ignores everything else.
  "m2.t": "Vigila a la cuadrilla e ignora todo lo demás.",
  // EN: It patrols a UTSA construction site on its own and checks on the crew. Onboard AI locks onto workers in high-visibility vests, ignores everything else, and sends an alert when someone may need help.
  "m2.p": "Patrulla por su cuenta una obra en construcción de UTSA y revisa a la cuadrilla. La IA a bordo se fija en los trabajadores con chaleco de alta visibilidad, ignora todo lo demás y envía una alerta cuando alguien podría necesitar ayuda.",
  // EN: No one walks to their car alone.
  "m3.title": "Nadie camina solo hasta su auto.",
  // EN: An escort from above, at night.
  "m3.t": "Una escolta desde el aire, de noche.",
  // EN: Campus safety can send the drone instead of an officer. It flies to the person who asked, follows 3 meters behind them to their car, and watches from above. If the radio link drops, it flies home on its own.
  "m3.p": "Seguridad del campus puede enviar el dron en lugar de un oficial. Vuela hasta la persona que lo pidió, la sigue a 3 metros hasta su auto y vigila desde arriba. Si se pierde el enlace de radio, vuelve a casa por su cuenta.",

  // ---- index.html: hardware -----------------------------------------------
  // EN: Hardware
  "hw.lab": "Hardware",
  // EN: Built from proven parts
  "hw.h2": "Hecho con piezas probadas",
  // EN: Rendered from the manufacturers' 3D models and our own board designs. The two circuit boards, the propellers and the radio housing were designed for this project.
  "hw.cap": "Renderizado a partir de los modelos 3D de los fabricantes y de nuestros propios diseños de placas. Las dos placas de circuito, las hélices y la carcasa de la radio se diseñaron para este proyecto.",
  // EN: Power distribution board
  "hw.pdb.h3": "Placa de distribución de energía",
  // EN: Top view of the Venator power distribution board, its bare copper rails running from the battery input to the four ESC connectors and the 12 V output
  "hw.pdb.alt": "Vista superior de la placa de distribución de energía de Venator, con sus pistas de cobre al descubierto desde la entrada de la batería hasta los cuatro conectores de los ESC y la salida de 12 V",
  // EN: Designed for this project. It carries the 4S battery to the four ESCs and makes the 12 V rail for the Jetson and the 5 V and 3.3 V rails for servos and sensors. Shown without its solder mask, so the copper shows.
  "hw.pdb.p": "Diseñada para este proyecto. Lleva la batería 4S a los cuatro ESC y genera la alimentación de 12 V para la Jetson y la de 5 V y 3.3 V para los servos y sensores. Se muestra sin su máscara de soldadura, para que se vea el cobre.",
  // EN: Handheld remote
  "hw.remote.h3": "Control remoto portátil",
  // EN: Top view of the Venator handheld remote: the Heltec LoRa board with its screen reading VENATOR, Connected: Ready to deploy, above a black knob and a white back button
  "hw.remote.alt": "Vista superior del control remoto portátil de Venator: la placa LoRa Heltec con su pantalla, que dice VENATOR, Connected: Ready to deploy, sobre una perilla negra y un botón blanco de regreso",
  // EN: Designed for this project. A Heltec WiFi LoRa 32 V3 with its screen, a knob and a back button, on its own board. It runs the motor tests and a 4 ft hover demo over the 915 MHz link, with no laptop. Shown without its antenna.
  "hw.remote.p": "Diseñado para este proyecto. Un Heltec WiFi LoRa 32 V3 con su pantalla, una perilla y un botón de regreso, en su propia placa. Hace las pruebas de motores y una demostración de vuelo estacionario a 4 pies por el enlace de 915 MHz, sin laptop. Se muestra sin su antena.",
  // EN: The Pixhawk 6X flight controller mounted flat on the carbon top plate, its connector bank facing the tail
  "hw.pixhawk.alt": "El controlador de vuelo Pixhawk 6X montado en plano sobre la placa superior de carbono, con el banco de conectores hacia la cola",
  // EN: The flight controller, mounted on the top plate. Built to FMUv6X, the open autopilot standard.
  "hw.pixhawk.p": "El controlador de vuelo, montado en la placa superior. Construido según FMUv6X, el estándar abierto de piloto automático.",
  // EN: NVIDIA Jetson Orin Nano & LoRa radio
  "hw.jetson.h3": "NVIDIA Jetson Orin Nano y radio LoRa",
  // EN: The Jetson Orin Nano developer kit mounted beneath the payload shelf, its heatsink fins, fan and connector bank facing the camera, with the Heltec LoRa stick standing on the shelf edge above it
  "hw.jetson.alt": "El kit de desarrollo Jetson Orin Nano montado bajo la bandeja de carga, con las aletas del disipador, el ventilador y el banco de conectores hacia la cámara, y el stick LoRa Heltec de pie en el borde de la bandeja, arriba",
  // EN: The onboard computer. It runs the AI and the command server and tells the flight controller what to do. The 915 MHz radio sits on the shelf above it: a Heltec Wireless Stick V3, shown here as the Lite model, without its small screen.
  "hw.jetson.p": "La computadora a bordo. Ejecuta la IA y el servidor de comandos, y le dice al controlador de vuelo qué hacer. La radio de 915 MHz va en la bandeja de arriba: un Heltec Wireless Stick V3, mostrado aquí como el modelo Lite, sin su pequeña pantalla.",
  // EN: The OAK-D Pro camera bolted to the forward bracket, its dark glass front panel facing the nose
  "hw.oakd.alt": "La cámara OAK-D Pro atornillada al soporte delantero, con su panel frontal de vidrio oscuro hacia la nariz",
  // EN: The eyes. A stereo depth camera that measures the distance to everything it sees, with infrared lighting for low light.
  "hw.oakd.p": "Los ojos. Una cámara estéreo de profundidad que mide la distancia a todo lo que ve, con iluminación infrarroja para poca luz.",
  // EN: The Holybro M10 GPS on its mast above the tail, raised clear of the airframe
  "hw.gps.alt": "El GPS Holybro M10 en su mástil sobre la cola, elevado por encima de la estructura",
  // EN: GPS, mounted high on the tail mast for a clear view of the sky.
  "hw.gps.p": "GPS, montado en lo alto del mástil de cola para una vista despejada del cielo.",
  // EN: 2216 motor and propeller
  "hw.motor.h3": "Motor 2216 y hélice",
  // EN: A 2216 brushless motor at the end of a carbon arm, carrying one ten inch propeller by its hub
  "hw.motor.alt": "Un motor sin escobillas 2216 en el extremo de un brazo de carbono, con una hélice de diez pulgadas sujeta por el cubo",
  // EN: One of four brushless motors, each turning a 10-inch propeller.
  "hw.motor.p": "Uno de los cuatro motores sin escobillas, cada uno con una hélice de 10 pulgadas.",
  // EN: Carbon arm and clamp
  "hw.arm.h3": "Brazo de carbono y abrazadera",
  // EN: A carbon fiber arm tube entering its molded two-piece clamp where the arm meets the body plate, with the clamp screws visible
  "hw.arm.alt": "Un tubo de fibra de carbono entrando en su abrazadera moldeada de dos piezas donde el brazo se une a la placa del cuerpo, con los tornillos a la vista",
  // EN: One of four carbon fiber arms on a 500 mm frame, each locked into the body by a two-piece clamp.
  "hw.arm.p": "Uno de los cuatro brazos de fibra de carbono de una estructura de 500 mm, cada uno fijado al cuerpo con una abrazadera de dos piezas.",

  // ---- index.html: views --------------------------------------------------
  // EN: Views
  "views.lab": "Vistas",
  // EN: Every angle
  "views.h2": "Desde todos los ángulos",
  // EN: Top, front, side and rear views of the same model. Open any view at full size.
  "views.cap": "Vistas superior, frontal, lateral y trasera del mismo modelo. Abre cualquiera a tamaño completo.",
  // EN: Top view
  "shots.top.name": "Vista superior",
  // EN: The aircraft from directly above, showing all four arms and propellers
  "shots.top.alt": "La aeronave vista directamente desde arriba, con los cuatro brazos y hélices",
  // EN: Front view
  "shots.front.name": "Vista frontal",
  // EN: The aircraft square on from the front, the OAK-D Pro camera centered under the body between the landing legs and the GPS mast above
  "shots.front.alt": "La aeronave de frente, con la cámara OAK-D Pro centrada bajo el cuerpo entre las patas de aterrizaje y el mástil del GPS arriba",
  // EN: Right side
  "shots.right.name": "Lado derecho",
  // EN: The aircraft from its right side, nose to the right, with the camera at the nose and the Jetson and GPS mast at the tail
  "shots.right.alt": "La aeronave desde su lado derecho, con la nariz a la derecha, la cámara en la nariz y la Jetson y el mástil del GPS en la cola",
  // EN: Rear view
  "shots.rear.name": "Vista trasera",
  // EN: The aircraft square on from the rear, the Jetson's heatsink centered under the body, the LoRa radio reaching out to one side and the GPS mast above
  "shots.rear.alt": "La aeronave desde atrás, con el disipador de la Jetson centrado bajo el cuerpo, la radio LoRa asomando hacia un lado y el mástil del GPS arriba",
  // EN: Left side
  "shots.left.name": "Lado izquierdo",
  // EN: The aircraft from its left side, nose to the left, with the camera at the nose and the Jetson and GPS mast at the tail
  "shots.left.alt": "La aeronave desde su lado izquierdo, con la nariz a la izquierda, la cámara en la nariz y la Jetson y el mástil del GPS en la cola",
  // EN: Previous view
  "shots.prev": "Vista anterior",
  // EN: Next view
  "shots.next": "Vista siguiente",
  // EN: Show the top view
  "shots.go.top": "Mostrar la vista superior",
  // EN: Show the front view
  "shots.go.front": "Mostrar la vista frontal",
  // EN: Show the right side
  "shots.go.right": "Mostrar el lado derecho",
  // EN: Show the rear view
  "shots.go.rear": "Mostrar la vista trasera",
  // EN: Show the left side
  "shots.go.left": "Mostrar el lado izquierdo",
  // EN: Close
  "shots.close": "Cerrar",
  // EN: Open this view at full size
  "shots.open": "Abrir esta vista a tamaño completo",

  // ---- how-it-works.html --------------------------------------------------
  // EN: How Venator works: long-range radio and onboard AI
  "hiw.title": "Cómo funciona Venator: radio de largo alcance e IA a bordo",
  // EN: How Venator works: a long-range radio link from a laptop, an onboard AI computer, and the capabilities built on top of it. No internet. No cell service.
  "hiw.desc": "Cómo funciona Venator: un enlace de radio de largo alcance desde una laptop, una computadora con IA a bordo y las capacidades construidas sobre ese enlace. Sin internet. Sin señal celular.",
  // EN: Laptop to propeller, with no network in between.
  "hiw.h1": "De la laptop a la hélice, sin ninguna red en medio.",
  // EN: How a command travels from a laptop to the aircraft, and the four capabilities built on that link.
  "hiw.p": "Cómo viaja un comando desde una laptop hasta la aeronave, y las cuatro capacidades construidas sobre ese enlace.",
  // EN: A search and rescue mission from start to finish. An operator fences a search area; a coverage path is planned to sweep every meter inside it; the view tilts from a map to show the aircraft flying at 40 meters within the fence; it sweeps the area and reroutes in real time around a tree in its lane; it detects a deer and logs it with its position without raising an alert; it finds a person who is not moving, holds station and sends an emergency with their coordinates over 915 MHz LoRa so medical help is dispatched; it finds a second person who is moving and follows at 3 meters; then it returns home and lands with the track and every detection.
  "hiw.mission_alt": "Una misión de búsqueda y rescate de principio a fin. Un operador delimita un área de búsqueda; se planifica una ruta de cobertura para barrer cada metro de su interior; la vista pasa de un mapa a mostrar la aeronave volando a 40 metros dentro del perímetro; barre el área y cambia de ruta en tiempo real para rodear un árbol en su carril; detecta un venado y lo registra con su posición sin dar alerta; encuentra a una persona que no se mueve, se mantiene en posición y envía una emergencia con sus coordenadas por LoRa a 915 MHz para que se despache ayuda médica; encuentra a una segunda persona que sí se mueve y la sigue a 3 metros; luego vuelve a casa y aterriza con el recorrido y cada detección.",
  // EN: How it works
  "how.lab": "Cómo funciona",
  // EN: Three parts. Two links.
  "how.h2": "Tres partes. Dos enlaces.",
  // EN: The laptop sends a command over a 915 MHz LoRa radio: long range, low power, no network needed. The onboard computer passes it to the flight controller and sends the answer back the same way.
  "how.cap": "La laptop envía un comando por una radio LoRa de 915 MHz: largo alcance, bajo consumo, sin necesidad de red. La computadora a bordo se lo pasa al controlador de vuelo y devuelve la respuesta por el mismo camino.",
  // EN: Three boxes: a laptop ground station, the Jetson on the drone, and the airframe. The laptop talks to the Jetson over 915 MHz LoRa, and the Jetson talks to the flight controller over MAVLink
  "how.system_alt": "Tres cajas: una estación terrestre en una laptop, la Jetson en el dron y la estructura de la aeronave. La laptop habla con la Jetson por LoRa a 915 MHz, y la Jetson habla con el controlador de vuelo por MAVLink",
  // EN: Pre-flight check
  "how.pre.h3": "Chequeo previo al vuelo",
  // EN: Every system reports in before the aircraft lifts off.
  "how.pre.p": "Cada sistema reporta antes de que la aeronave despegue.",
  // EN: System self-test: radio, link, flight controller, camera, compute, C2, GPS and outdoor flight all OK; then ready, and the aircraft lifts
  "how.pre.alt": "Autodiagnóstico del sistema: radio, enlace, controlador de vuelo, cámara, cómputo, C2, GPS y vuelo en exteriores, todos OK; luego lista, y la aeronave despega",
  // EN: What it does
  "what.h2": "Lo que hace",
  // EN: Four capabilities on one radio link, with one safety rule: if the link drops for more than four seconds, the aircraft flies home on its own.
  "what.cap": "Cuatro capacidades sobre un solo enlace de radio, con una regla de seguridad: si el enlace se cae por más de cuatro segundos, la aeronave vuelve a casa por su cuenta.",
  // EN: Follow a person
  "cap.follow.h3": "Seguir a una persona",
  // EN: Stays 3 m behind until told to stop. If it loses sight, it hovers instead of guessing.
  "cap.follow.p": "Se mantiene 3 m detrás hasta que se le indique parar. Si la pierde de vista, se queda en vuelo estacionario en lugar de adivinar.",
  // EN: A laptop commands the drone over 915 MHz LoRa; it takes off, follows a person at 3 m, and returns home when the link drops
  "cap.follow.alt": "Una laptop comanda el dron por LoRa a 915 MHz; despega, sigue a una persona a 3 m y vuelve a casa cuando se cae el enlace",
  // EN: Patrol a route
  "cap.patrol.h3": "Patrullar una ruta",
  // EN: Send a route over the radio. Every point is confirmed, and nothing spins up until you confirm a second time.
  "cap.patrol.p": "Envía una ruta por la radio. Cada punto se confirma, y nada arranca hasta que confirmas una segunda vez.",
  // EN: Four coordinates uploaded over LoRa, validated, armed, flown as a circuit with a deviation around an obstacle, then returns to launch
  "cap.patrol.alt": "Cuatro coordenadas cargadas por LoRa, validadas, armado, un circuito volado con un desvío alrededor de un obstáculo, y luego regreso al punto de despegue",
  // EN: Message every station at once
  "cap.mesh.h3": "Enviar un mensaje a todas las estaciones a la vez",
  // EN: One radio message reaches every station in range at the same moment, and each one confirms it arrived.
  "cap.mesh.p": "Un solo mensaje de radio llega a todas las estaciones al alcance en el mismo instante, y cada una confirma que lo recibió.",
  // EN: One LoRa transmission reaching the ground station and the aircraft at the same instant, with phones loading a page from the machine holding the radio
  "cap.mesh.alt": "Una sola transmisión LoRa que llega a la estación terrestre y a la aeronave en el mismo instante, con teléfonos cargando una página desde la máquina que tiene la radio",
  // EN: Steer around obstacles
  "cap.avoid.h3": "Esquivar obstáculos",
  // EN: The depth camera spots what's ahead. The aircraft brakes, goes around it, and gets back on course.
  "cap.avoid.p": "La cámara de profundidad detecta lo que hay adelante. La aeronave frena, lo rodea y retoma el rumbo.",
  // EN: Forward depth from the camera finds an obstacle ahead; the aircraft brakes, deviates around it and returns to the original track
  "cap.avoid.alt": "La profundidad frontal de la cámara encuentra un obstáculo adelante; la aeronave frena, lo rodea y vuelve a la trayectoria original",

  // ---- timeline.html ---------------------------------------------------
  // EN: Timeline: the team behind Venator
  "tl.title": "Cronología: el equipo detrás de Venator",
  // EN: Who built Venator and what each of us did, in order: the circuit boards, the power board, the gimbal math, the telemetry link, the radio and the onboard AI. Team 6 at UTSA.
  "tl.desc": "Quién construyó Venator y qué hizo cada uno, en orden: las placas de circuito, la placa de energía, las matemáticas del gimbal, el enlace de telemetría, la radio y la IA a bordo. Equipo 6 de UTSA.",
  // EN: Team 6
  "tl.team6": "Equipo 6",
  // EN: Five engineers.
  "tl.beat1": "Cinco ingenieros.",
  // EN: One aircraft.
  "tl.beat2": "Una aeronave.",
  // EN: Venator is built by Team 6 at UTSA. Here is what each of us built, in the order it happened, and who we are.
  "tl.p": "Venator lo construye el Equipo 6 de UTSA. Aquí está lo que construyó cada uno de nosotros, en el orden en que pasó, y quiénes somos.",
  // EN: Meet the team
  "tl.cta": "Conoce al equipo",
  // EN: Built part by part
  "tl.h2": "Construido pieza por pieza",
  // EN: One track per teammate, each in the order the work happened. Dates come from our Demo B review on October 23, 2026, and from the project's commit history.
  "tl.cap": "Una línea por integrante, cada una en el orden en que se hizo el trabajo. Las fechas vienen de nuestra revisión Demo B del 23 de octubre de 2026 y del historial de commits del proyecto.",
  // EN: Teammates
  "tl.jump": "Integrantes",
  // EN: Ground control & networking
  "tl.david.role": "Control terrestre y redes",
  // EN: Phase 3 · Implementation
  "tl.when.p3": "Fase 3 · Implementación",
  // EN: Two boards, in 3D
  "tl.david.e1.h": "Dos placas, en 3D",
  // EN: Modeled both of our radio boards in 3D: the ESP32 board in the handheld remote and the Pico board in the gateway.
  "tl.david.e1.p": "Modeló en 3D nuestras dos placas de radio: la placa ESP32 del control remoto portátil y la placa Pico de la puerta de enlace.",
  // EN: 3D model of the handheld remote's board: the Heltec ESP32 LoRa module with its screen, above a knob and a back button
  "tl.david.e1.alt1": "Modelo 3D de la placa del control remoto portátil: el módulo LoRa Heltec ESP32 con su pantalla, sobre una perilla y un botón de regreso",
  // EN: 3D model of the gateway board: a large 2.42 inch screen above a knob and a back button
  "tl.david.e1.alt2": "Modelo 3D de la placa de la puerta de enlace: una pantalla grande de 2.42 pulgadas sobre una perilla y un botón de regreso",
  // EN: Cases, designed and printed
  "tl.david.e2.h": "Carcasas, diseñadas e impresas",
  // EN: Designed a case for each board in Fusion 360, then 3D-printed them.
  "tl.david.e2.p": "Diseñó una carcasa para cada placa en Fusion 360 y luego las imprimió en 3D.",
  // EN: A 3D-printed case, blue on an orange base, with the board's screen and knob showing through the top, on a workbench
  "tl.david.e2.alt": "Una carcasa impresa en 3D, azul sobre una base naranja, con la pantalla y la perilla de la placa asomando por arriba, sobre una mesa de trabajo",
  // EN: Oct 23, 2026 · Demo B
  "tl.when.demob": "23 oct 2026 · Demo B",
  // EN: Firmware and the radio bridge
  "tl.david.e3.h": "Firmware y el puente de radio",
  // EN: Took on the ESP32 firmware and the link between the Pico board and the drone's Heltec radio, two radios that frame LoRa packets differently.
  "tl.david.e3.p": "Se encargó del firmware del ESP32 y del enlace entre la placa Pico y la radio Heltec del dron, dos radios que arman los paquetes LoRa de forma distinta.",
  // EN: Also worked on
  "tl.also": "También trabajó en",
  // EN: Power system and board fabrication, with Grant and Vincent
  "tl.david.a1": "Sistema de energía y fabricación de placas, con Grant y Vincent",
  // EN: Pixhawk setup and tuning, with Grant
  "tl.david.a2": "Configuración y ajuste del Pixhawk, con Grant",
  // EN: UART integration, with Grant
  "tl.david.a3": "Integración UART, con Grant",
  // EN: Ground control interface
  "tl.david.a4": "Interfaz de control terrestre",
  // EN: Video streaming, with Sergio
  "tl.david.a5": "Transmisión de video, con Sergio",
  // EN: Integration testing, with Grant and Leonel
  "tl.david.a6": "Pruebas de integración, con Grant y Leonel",
  // EN: Flight dynamics & avionics
  "tl.grant.role": "Dinámica de vuelo y aviónica",
  // EN: Where everything sits
  "tl.grant.e1.h": "Dónde va cada cosa",
  // EN: Sketched how the GPS, the Pixhawk, the downward lidar and the laser rangefinder on its servo sit relative to each other, so a distance measured from the drone can become a position on the ground.
  "tl.grant.e1.p": "Dibujó cómo se ubican entre sí el GPS, el Pixhawk, el lidar hacia abajo y el telémetro láser sobre su servo, para que una distancia medida desde el dron se pueda convertir en una posición en el suelo.",
  // EN: Whiteboard sketch of the drone from the side: the GPS, the Pixhawk, the downward lidar and the rangefinder on its servo, with notes on the offsets between them
  "tl.grant.e1.alt": "Dibujo en pizarrón del dron de lado: el GPS, el Pixhawk, el lidar hacia abajo y el telémetro sobre su servo, con notas sobre las distancias entre ellos",
  // EN: The math, then the test
  "tl.grant.e2.h": "Primero las matemáticas, luego la prueba",
  // EN: Worked out the geometry from the drone's height and the rangefinder's reading to the target's position, then tested the laser rangefinder and the equation that sets the servo's angle.
  "tl.grant.e2.p": "Resolvió la geometría que va de la altura del dron y la lectura del telémetro a la posición del objetivo, y luego probó el telémetro láser y la ecuación que fija el ángulo del servo.",
  // EN: Whiteboard math: the lidar's height and the rangefinder's reading form a right triangle, solved for the distance along the ground
  "tl.grant.e2.alt": "Matemáticas en pizarrón: la altura del lidar y la lectura del telémetro forman un triángulo rectángulo, resuelto para la distancia sobre el suelo",
  // EN: A servo stands in for the gimbal
  "tl.grant.e3.h": "Un servo en lugar del gimbal",
  // EN: Tested a servo standing in for the gimbal's own, with potentiometers simulating the values it will read from the Pixhawk.
  "tl.grant.e3.p": "Probó un servo que simula el del gimbal, con potenciómetros que simulan los valores que leerá del Pixhawk.",
  // EN: Whiteboard notes on the servo: how its angle follows the PWM signal, and how the potentiometer readings map onto it
  "tl.grant.e3.alt": "Notas en pizarrón sobre el servo: cómo su ángulo sigue la señal PWM y cómo se traducen las lecturas del potenciómetro",
  // EN: Onto the real gimbal
  "tl.grant.e4.h": "Al gimbal real",
  // EN: Testing the servos on the gimbal itself, and bringing the lidar's data into the Pixhawk and the ground station. Next: the test code onto the Jetson, and the infrared camera.
  "tl.grant.e4.p": "Probando los servos en el propio gimbal e integrando los datos del lidar al Pixhawk y a la estación terrestre. Lo siguiente: pasar el código de prueba a la Jetson y la cámara infrarroja.",
  // EN: Power system and board fabrication, with David and Vincent
  "tl.grant.a1": "Sistema de energía y fabricación de placas, con David y Vincent",
  // EN: Pixhawk setup and tuning, with David
  "tl.grant.a2": "Configuración y ajuste del Pixhawk, con David",
  // EN: UART integration, with David
  "tl.grant.a3": "Integración UART, con David",
  // EN: System integration, with Leonel and Vincent
  "tl.grant.a4": "Integración del sistema, con Leonel y Vincent",
  // EN: Sensor and power testing, with Vincent
  "tl.grant.a5": "Pruebas de sensores y energía, con Vincent",
  // EN: Integration testing, with David and Leonel
  "tl.grant.a6": "Pruebas de integración, con David y Leonel",
  // EN: Flight testing, with Leonel
  "tl.grant.a7": "Pruebas de vuelo, con Leonel",
  // EN: Electromechanical & power systems
  "tl.vincent.role": "Sistemas electromecánicos y de energía",
  // EN: The power distribution board
  "tl.vincent.e1.h": "La placa de distribución de energía",
  // EN: Designed the board that carries the 4S battery to the four ESCs and makes the 12 V, 5 V and 3.3 V rails for the Jetson, the servos and the sensors.
  "tl.vincent.e1.p": "Diseñó la placa que lleva la batería 4S a los cuatro ESC y genera la alimentación de 12 V, 5 V y 3.3 V para la Jetson, los servos y los sensores.",
  // EN: Render of the power distribution board: a green board with power connectors along its edges and its regulators near the center
  "tl.vincent.e1.alt": "Imagen renderizada de la placa de distribución de energía: una placa verde con conectores de energía en sus bordes y los reguladores cerca del centro",
  // EN: The board arrives
  "tl.vincent.e2.h": "Llega la placa",
  // EN: The fabricated board had just arrived, and soldering was under way. The smallest surface-mount parts were next, with David, a hot plate and a digital microscope.
  "tl.vincent.e2.p": "La placa fabricada acababa de llegar y la soldadura estaba en marcha. Lo siguiente eran las piezas de montaje superficial más pequeñas, con David, una plancha caliente y un microscopio digital.",
  // EN: Power system and board fabrication, with David and Grant
  "tl.vincent.a1": "Sistema de energía y fabricación de placas, con David y Grant",
  // EN: System integration, with Grant and Leonel
  "tl.vincent.a2": "Integración del sistema, con Grant y Leonel",
  // EN: Sensor and power testing, with Grant
  "tl.vincent.a3": "Pruebas de sensores y energía, con Grant",
  // EN: Middleware & system integration
  "tl.leonel.role": "Middleware e integración de sistemas",
  // EN: A home for the Jetson
  "tl.leonel.e1.h": "Un lugar para la Jetson",
  // EN: Designed and installed the Jetson Orin Nano's enclosure and its mount on the airframe.
  "tl.leonel.e1.p": "Diseñó e instaló la carcasa de la Jetson Orin Nano y su soporte en la estructura de la aeronave.",
  // EN: The Jetson in its orange 3D-printed enclosure, mounted under the drone's frame
  "tl.leonel.e1.alt": "La Jetson en su carcasa naranja impresa en 3D, montada bajo la estructura del dron",
  // EN: A two-axis camera gimbal
  "tl.leonel.e2.h": "Un gimbal de cámara de dos ejes",
  // EN: Designed, printed and assembled the servo gimbal that carries the camera.
  "tl.leonel.e2.p": "Diseñó, imprimió y armó el gimbal de servos que lleva la cámara.",
  // EN: The two-axis servo gimbal on the drone, holding the OAK-D Pro camera in a black frame under an orange mount
  "tl.leonel.e2.alt": "El gimbal de servos de dos ejes en el dron, con la cámara OAK-D Pro en un marco negro bajo un soporte naranja",
  // EN: Live telemetry in the GUI
  "tl.leonel.e3.h": "Telemetría en vivo en la interfaz",
  // EN: Connected the Pixhawk 6X to the VENATOR GUI over a SiK telemetry radio. The port is found on its own; roll, pitch, heading, battery and flight mode update 10 times a second, and the downward lidar's distance to the floor 5 times a second.
  "tl.leonel.e3.p": "Conectó el Pixhawk 6X a la interfaz de VENATOR mediante una radio de telemetría SiK. El puerto se detecta solo; el alabeo, el cabeceo, el rumbo, la batería y el modo de vuelo se actualizan 10 veces por segundo, y la distancia al piso del lidar inferior, 5 veces por segundo.",
  // EN: The SiK telemetry radio and its antenna, wired to the Pixhawk on the drone's top plate
  "tl.leonel.e3.alt": "La radio de telemetría SiK y su antena, conectadas al Pixhawk en la placa superior del dron",
  // EN: Checked on the bench
  "tl.leonel.e4.h": "Verificado en el banco de pruebas",
  // EN: Verified the wireless MAVLink connection and live telemetry through the SiK radio, and the lidar's readings feeding PX4's height estimate. Next: outdoor range tests, and the camera's view in the GUI.
  "tl.leonel.e4.p": "Verificó la conexión MAVLink inalámbrica y la telemetría en vivo por la radio SiK, y que las lecturas del lidar alimentan la estimación de altura de PX4. Lo siguiente: pruebas de alcance en exteriores y la vista de la cámara en la interfaz.",
  // EN: Jetson setup, ROS 2 and AI, with Sergio
  "tl.leonel.a1": "Configuración de la Jetson, ROS 2 e IA, con Sergio",
  // EN: System integration, with Grant and Vincent
  "tl.leonel.a2": "Integración del sistema, con Grant y Vincent",
  // EN: Integration testing, with David and Grant
  "tl.leonel.a3": "Pruebas de integración, con David y Grant",
  // EN: Flight testing, with Grant
  "tl.leonel.a4": "Pruebas de vuelo, con Grant",
  // EN: AI detection testing, with Sergio
  "tl.leonel.a5": "Pruebas de detección con IA, con Sergio",
  // EN: Perception & edge AI
  "tl.sergio.role": "Percepción e IA embarcada",
  // EN: Oct 9, 2026
  "tl.sergio.e1.when": "9 oct 2026",
  // EN: Finding people and animals
  "tl.sergio.e1.h": "Encontrar personas y animales",
  // EN: Switched the onboard detector to MegaDetector v6, which finds people and animals, and gave it a memory: each detection keeps a track ID, a confidence and a distance.
  "tl.sergio.e1.p": "Cambió el detector a bordo a MegaDetector v6, que encuentra personas y animales, y le dio memoria: cada detección conserva un ID de seguimiento, una confianza y una distancia.",
  // EN: Testing the detector: the OAK-D Pro camera held up to a laptop screen full of cattle photos, with the live dashboard on the monitor behind it
  "tl.sergio.e1.alt": "Prueba del detector: la cámara OAK-D Pro frente a una laptop llena de fotos de ganado, con el panel en vivo en el monitor de atrás",
  // EN: Oct 21, 2026
  "tl.sergio.e2.when": "21 oct 2026",
  // EN: Motors spin over our own radio
  "tl.sergio.e2.h": "Los motores giran con nuestra propia radio",
  // EN: Wrote the handheld remote's menu (test each motor, test all four, hover, status) and spun the motors on the real aircraft from it, over the 915 MHz link. The same day, the Pico gateway learned to talk to the drone.
  "tl.sergio.e2.p": "Escribió el menú del control remoto portátil (probar cada motor, probar los cuatro, vuelo estacionario, estado) y desde él hizo girar los motores de la aeronave real por el enlace de 915 MHz. Ese mismo día, la puerta de enlace Pico aprendió a hablar con el dron.",
  // EN: The handheld remote in its orange case, its screen reading VENATOR, Looking for the drone, wired to a Heltec Wireless Stick showing LINK UP
  "tl.sergio.e2.alt": "El control remoto portátil en su carcasa naranja, con la pantalla que dice VENATOR, Looking for the drone, conectado a un Heltec Wireless Stick que muestra LINK UP",
  // EN: The numbers at Demo B
  "tl.sergio.e3.h": "Las cifras de la Demo B",
  // EN: The LoRa link delivered 20 of 20 packets with no loss, at about 435 ms round trip. The OAK-D Pro drew about 3.1 W, and the whole system ran inside the Jetson's 7 W power mode, light enough for battery flight.
  "tl.sergio.e3.p": "El enlace LoRa entregó 20 de 20 paquetes sin pérdidas, con unos 435 ms de ida y vuelta. La OAK-D Pro consumió unos 3.1 W y todo el sistema funcionó dentro del modo de 7 W de la Jetson, apto para volar con batería.",
  // EN: A USB power meter reading 3.1 W, plugged in line with the OAK-D Pro camera on the drone
  "tl.sergio.e3.alt1": "Un medidor de potencia USB que marca 3.1 W, conectado en línea con la cámara OAK-D Pro en el dron",
  // EN: The Heltec Wireless Stick plugged into the Jetson's orange case on the bench
  "tl.sergio.e3.alt2": "El Heltec Wireless Stick conectado a la carcasa naranja de la Jetson en el banco de pruebas",
  // EN: Nov 6, 2026
  "tl.sergio.e4.when": "6 nov 2026",
  // EN: Find the worker in the yellow vest
  "tl.sergio.e4.h": "Encontrar al trabajador del chaleco amarillo",
  // EN: Taught the camera to lock onto a yellow construction vest and ignore everyone else, with search controls and calibration on the operator's page and an alert that sounds on iPhones too.
  "tl.sergio.e4.p": "Enseñó a la cámara a fijarse en un chaleco amarillo de construcción e ignorar a todos los demás, con controles de búsqueda y calibración en la página del operador y una alerta que también suena en iPhone.",
  // EN: Nov 19–20, 2026
  "tl.sergio.e5.when": "19–20 nov 2026",
  // EN: A tougher link, a 4 ft hover
  "tl.sergio.e5.h": "Un enlace más robusto, un vuelo a 4 pies",
  // EN: Hardened the LoRa command link end to end, added an indoor hover mode, and raised the remote's hover demo to 4 ft (1.22 m).
  "tl.sergio.e5.p": "Reforzó de punta a punta el enlace de comandos LoRa, agregó un modo de vuelo estacionario en interiores y subió la demostración de vuelo del control remoto a 4 pies (1.22 m).",
  // EN: Buying the parts
  "tl.sergio.a1": "Compra de componentes",
  // EN: Jetson setup, ROS 2 and AI, with Leonel
  "tl.sergio.a2": "Configuración de la Jetson, ROS 2 e IA, con Leonel",
  // EN: Video streaming, with David
  "tl.sergio.a3": "Transmisión de video, con David",
  // EN: AI detection testing, with Leonel
  "tl.sergio.a4": "Pruebas de detección con IA, con Leonel",
  // EN: Behind the build
  "tl.fun.lab": "Detrás de la construcción",
  // EN: Building it, together
  "tl.fun.h2": "Construyéndolo juntos",
  // EN: Soldering, code reviews and a lot of cables. The build, as it happened.
  "tl.fun.cap": "Soldadura, revisiones de código y muchos cables. La construcción, tal como pasó.",
  // EN: Mid-build, still smiling
  "tl.fun.c1": "A media construcción, y sonriendo",
  // EN: Two teammates at the workbench smiling at the camera, one seated with a yellow safety vest across their knee, the drone and a laptop of code beside them
  "tl.fun.alt1": "Dos integrantes del equipo en el banco de trabajo sonriendo a la cámara, uno sentado con un chaleco de seguridad amarillo sobre la rodilla, junto al dron y una laptop con código",
  // EN: Talking it through at the bench
  "tl.fun.c2": "Revisándolo juntos en el banco",
  // EN: One teammate points at the screen while another looks on, the drone on the bench beside them
  "tl.fun.alt2": "Un integrante señala la pantalla mientras otro observa, con el dron en el banco a su lado",
  // EN: Hot plate, microscope, steady hands
  "tl.fun.c3": "Plancha caliente, microscopio y pulso firme",
  // EN: A teammate in a cap and headphones solders a green circuit board on a hot plate, watching the work on a digital microscope's screen
  "tl.fun.alt3": "Un integrante con gorra y audífonos suelda una placa verde sobre una plancha caliente, mirando el trabajo en la pantalla de un microscopio digital",
  // EN: The team
  "tl.team.h2": "El equipo",
  // EN: Five engineering students at UTSA, each owning one part of the system.
  "tl.team.cap": "Cinco estudiantes de ingeniería de UTSA, cada uno a cargo de una parte del sistema.",
  // EN: Experience
  "tl.exp": "Experiencia",
  // EN: EE intern at Modular One Tech; student engineer at Southwest Research Institute
  "tl.david.exp": "Practicante de ingeniería eléctrica en Modular One Tech; ingeniero estudiante en Southwest Research Institute",
  // EN: Motors and software protocols
  "tl.grant.exp": "Motores y protocolos de software",
  // EN: EE intern at TAMUCC; PCB design and fabrication
  "tl.vincent.exp": "Practicante de ingeniería eléctrica en TAMUCC; diseño y fabricación de PCB",
  // EN: Project designer at Alterman; embedded systems and robotics platforms
  "tl.leonel.exp": "Diseñador de proyectos en Alterman; sistemas embebidos y plataformas robóticas",
  // EN: DepthAI scripts, UART and MAVLink protocols
  "tl.sergio.exp": "Scripts de DepthAI y protocolos UART y MAVLink"
};
