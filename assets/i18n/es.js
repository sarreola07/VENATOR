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
  // EN: Rendered from the manufacturers' 3D models and our own designs. The two circuit boards, the propellers, the radio housing and the camera gimbal were designed for this project.
  "hw.cap": "Renderizado a partir de los modelos 3D de los fabricantes y de nuestros propios diseños. Las dos placas de circuito, las hélices, la carcasa de la radio y el gimbal de la cámara se diseñaron para este proyecto.",
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
  // EN: The OAK-D Pro camera in its 3D-printed pan-and-tilt gimbal, hanging from the two payload rails under the airframe, its dark glass front panel facing forward
  "hw.oakd.alt": "La cámara OAK-D Pro en su gimbal de giro e inclinación impreso en 3D, colgada de los dos rieles de carga bajo la estructura, con su panel frontal de vidrio oscuro hacia el frente",
  // EN: The eyes. A stereo depth camera that measures the distance to everything it sees, with infrared lighting for low light. It rides in a pan-and-tilt gimbal designed and 3D-printed for this project, shown here with generic stand-ins for its servos.
  "hw.oakd.p": "Los ojos. Una cámara estéreo de profundidad que mide la distancia a todo lo que ve, con iluminación infrarroja para poca luz. Va montada en un gimbal de giro e inclinación diseñado e impreso en 3D para este proyecto, mostrado aquí con servos genéricos en lugar de los reales.",
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
  "cap.avoid.alt": "La profundidad frontal de la cámara encuentra un obstáculo adelante; la aeronave frena, lo rodea y vuelve a la trayectoria original"
};
