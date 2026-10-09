// The wrenchroom HTML view: draws what wrenchroom.view wrote, and keeps the selection.
//
// Every decision about colours, highlights, states and tool positions was made in
// Python (wrenchroom/view/__init__.py), where the tests can see it; this script
// only draws them. Names are the model's: they reach the page through textContent
// only, never as markup.
//
// After every change it writes what it drew into #drawn, as JSON of indices into
// the data (never names), so a test can read the scene from a headless browser.
(function () {
  "use strict";

  const SCHEMA = 1;
  const GHOST = 0.14; // opacity of a part that isn't the subject while one is selected
  const IGNORED = 0.35; // opacity of a part the sidecar ignores
  const OTHER_FASTENER = 0.5; // opacity of other fasteners while one is selected
  const BLOCKER = 0.7; // opacity of a highlighted blocker: plainly there, and the
  // fastener and tool behind it still show (a wall over a screw would hide both)

  const data = JSON.parse(document.getElementById("wrenchroom-data").textContent);
  const C = data.colours;
  const $ = (id) => document.getElementById(id);
  const drawn = $("drawn");
  if (data.schema !== SCHEMA) {
    drawn.textContent = JSON.stringify({ ready: false, error: "schema " + data.schema });
    return;
  }
  const byName = new Map(data.fasteners.map((f, index) => [f.name, index]));

  let selected = null; // index into data.fasteners
  let isolated = null; // index into the selected fastener's attempts

  // ------------------------------------------------------------------ panel

  function el(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined && text !== null) node.textContent = text;
    if (className) node.className = className;
    return node;
  }

  function swatch(colour) {
    const node = el("span", null, "swatch");
    node.style.background = colour;
    return node;
  }

  $("model").textContent = data.model;
  $("summary").textContent = data.summary_text;
  for (const [key, text] of data.legend) {
    const item = el("li");
    item.append(swatch(C[key]), el("span", text));
    $("legend").append(item);
  }
  data.fasteners.forEach((f, index) => {
    const button = el("button");
    button.type = "button";
    button.append(swatch(f.colour), el("span", f.label, "name"), el("span", f.verdict, "verdict"));
    button.addEventListener("click", () => select(index));
    const item = el("li");
    item.append(button);
    $("fasteners").append(item);
  });
  $("tools-summary").textContent = data.tools.header;
  for (const use of data.tools.uses) {
    const item = el("li");
    item.append(el("span", use.tool, "name"), el("span", " x" + use.count, "count"));
    if (use.said.length) item.append(el("span", " " + use.said.join("; "), "muted"));
    $("tools").append(item);
  }
  for (const line of data.tools.apart) $("tools").append(el("li", line, "muted"));
  $("back").addEventListener("click", () => select(null));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") select(null);
  });

  function showDetail(f) {
    $("detail").hidden = f === null;
    $("list").hidden = f !== null;
    if (f === null) return;
    $("name").textContent = f.label;
    $("headline").textContent = f.headline;
    $("reason").hidden = !f.reason;
    $("reason").textContent = f.reason ? "Why: " + f.reason : "";
    const inWay = $("inway");
    inWay.hidden = f.in_way.length === 0;
    inWay.replaceChildren();
    if (f.in_way.length) {
      const label = f.verdict === "stuck" ? "In its way out: " : "In the way: ";
      inWay.append(swatch(C.blocker), el("span", label), el("span", f.in_way.join(", "), "name"));
    }
    const view = data.views[f.view];
    $("state").hidden = view.state === null;
    $("state").textContent = view.state === null ? "" : "Drawn in state " + view.label + ".";
    const list = $("attempts");
    list.replaceChildren();
    f.attempts.forEach((attempt, index) => {
      const button = el("button", attempt.text);
      button.type = "button";
      button.setAttribute("aria-pressed", String(isolated === index));
      button.addEventListener("click", () => isolate(index));
      const item = el("li");
      item.append(button);
      list.append(item);
    });
    if (f.attempts.length === 0) list.append(el("li", "None: nothing was tried.", "muted"));
  }

  function status(text) {
    $("status").textContent = text;
  }

  // ------------------------------------------------------------------ scene

  let renderer = null;
  let webglError = null;
  const canvas = $("view");
  try {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  } catch (error) {
    webglError = String((error && error.message) || error);
    $("nogl").hidden = false;
    $("nogl").textContent =
      "This browser could not start WebGL, so the 3D view is off. The list and " +
      "every attempt are still here.";
  }

  function decode(b64) {
    const text = atob(b64);
    const bytes = new Uint8Array(text.length);
    for (let i = 0; i < text.length; i++) bytes[i] = text.charCodeAt(i);
    return bytes.buffer;
  }

  const geometries = new Map();
  function geometry(index) {
    let made = geometries.get(index);
    if (!made) {
      const shape = data.shapes[index];
      made = new THREE.BufferGeometry();
      made.setAttribute("position", new THREE.BufferAttribute(new Float32Array(decode(shape.p)), 3));
      made.setIndex(new THREE.BufferAttribute(new Uint32Array(decode(shape.i)), 1));
      made.computeVertexNormals();
      geometries.set(index, made);
    }
    return made;
  }

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(C.background);
  const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 1000);
  camera.up.set(0, 0, 1);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8f98, 2.2));
  const headlight = new THREE.DirectionalLight(0xffffff, 1.4);
  headlight.position.set(0.4, 0.6, 1);
  camera.add(headlight);
  scene.add(camera);

  const edgeMaterial = new THREE.LineBasicMaterial({ color: 0x3d434b });
  const partMeshes = data.parts.map((part, index) => {
    if (part.shape === null) return null;
    const material = new THREE.MeshLambertMaterial({ color: C.part, side: THREE.DoubleSide });
    const mesh = new THREE.Mesh(geometry(part.shape), material);
    mesh.userData.part = index;
    const edges = new THREE.LineSegments(new THREE.EdgesGeometry(mesh.geometry, 35), edgeMaterial);
    mesh.add(edges);
    mesh.userData.edges = edges;
    scene.add(mesh);
    return mesh;
  });

  const tools = new THREE.Group();
  scene.add(tools);
  function toolMaterial(colour, opacity) {
    return new THREE.MeshLambertMaterial({
      color: colour,
      transparent: true,
      opacity,
      depthWrite: false,
      side: THREE.DoubleSide,
      flatShading: true,
    });
  }
  const hitMaterial = toolMaterial(C["probe-hit"], 0.4);
  const clearMaterial = toolMaterial(C["probe-clear"], 0.22);

  let controls = null;
  if (renderer) {
    controls = new THREE.OrbitControls(camera, canvas);
    controls.addEventListener("change", render);
  }

  function render() {
    if (renderer) renderer.render(scene, camera);
  }

  function resize() {
    if (!renderer) return;
    const stage = $("stage");
    const width = Math.max(1, stage.clientWidth);
    const height = Math.max(1, stage.clientHeight);
    renderer.setPixelRatio(window.devicePixelRatio || 1);
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    render();
  }
  window.addEventListener("resize", resize);

  // ------------------------------------------------------------- drawing

  function paint(mesh, colour, opacity) {
    mesh.material.color.set(colour);
    mesh.material.opacity = opacity;
    mesh.material.transparent = opacity < 1;
    mesh.material.depthWrite = opacity >= 1;
    mesh.userData.edges.visible = opacity >= OTHER_FASTENER;
  }

  function addProbe(probe) {
    const placements = new Float32Array(decode(probe.m));
    probe.s.forEach((shape, k) => {
      const mesh = new THREE.Mesh(geometry(shape), probe.hit ? hitMaterial : clearMaterial);
      const m = placements.subarray(12 * k, 12 * k + 12);
      mesh.matrixAutoUpdate = false;
      mesh.matrix.set(m[0], m[1], m[2], m[3], m[4], m[5], m[6], m[7], m[8], m[9], m[10], m[11], 0, 0, 0, 1);
      mesh.matrixWorldNeedsUpdate = true;
      mesh.userData.hit = probe.hit;
      tools.add(mesh);
    });
  }

  function apply(reframe) {
    const f = selected === null ? null : data.fasteners[selected];
    const viewIndex = f ? f.view : data.overview;
    const visible = new Set(data.views[viewIndex].parts);
    let highlight = [];
    if (f) highlight = isolated === null ? f.highlight : f.attempts[isolated].highlight;
    const highlighted = new Set(highlight);

    data.parts.forEach((part, index) => {
      const mesh = partMeshes[index];
      if (!mesh) return;
      mesh.visible = visible.has(index);
      const owner = byName.get(part.owner ?? part.name);
      let colour = owner === undefined ? C.part : data.fasteners[owner].colour;
      let opacity = part.role === "ignored" ? IGNORED : 1;
      if (f) {
        if (highlighted.has(index)) {
          colour = C.blocker;
          opacity = BLOCKER;
        } else if ((part.owner ?? part.name) !== f.name) {
          opacity = owner === undefined ? GHOST : OTHER_FASTENER;
        }
      }
      paint(mesh, colour, opacity);
    });

    tools.clear();
    if (f) {
      const attempts = isolated === null ? f.attempts : [f.attempts[isolated]];
      for (const attempt of attempts) for (const probe of attempt.probes) addProbe(probe);
      if (f.way_out && isolated === null) addProbe(f.way_out);
    }

    showDetail(f);
    if (reframe) frame(f, visible);
    render();
    record(viewIndex);
  }

  const box = new THREE.Box3();
  const sphere = new THREE.Sphere();
  const direction = new THREE.Vector3(1, -1.4, 0.9).normalize();
  function frame(f, visible) {
    scene.updateMatrixWorld(true);
    box.makeEmpty();
    if (f) {
      const own = f.part === null ? null : partMeshes[f.part];
      if (own) box.expandByObject(own);
      for (const child of tools.children) box.expandByObject(child);
    }
    if (box.isEmpty()) {
      partMeshes.forEach((mesh, index) => {
        if (mesh && visible.has(index)) box.expandByObject(mesh);
      });
    }
    if (box.isEmpty()) return;
    box.getBoundingSphere(sphere);
    const radius = Math.max(sphere.radius, 1);
    const fov = (camera.fov * Math.PI) / 180;
    const fit = Math.min(fov, 2 * Math.atan(Math.tan(fov / 2) * camera.aspect));
    const distance = (radius / Math.sin(fit / 2)) * 1.1;
    if (controls) {
      const from = camera.position.clone().sub(controls.target);
      if (from.lengthSq() > 0) direction.copy(from.normalize());
      controls.target.copy(sphere.center);
    }
    camera.position.copy(sphere.center).addScaledVector(direction, distance);
    camera.near = Math.max(distance / 1000, 0.01);
    camera.far = distance * 10 + radius * 4;
    camera.updateProjectionMatrix();
    if (controls) controls.update();
  }

  function record(viewIndex) {
    const parts = [];
    partMeshes.forEach((mesh, index) => {
      if (mesh && mesh.visible) {
        parts.push([index, "#" + mesh.material.color.getHexString(), mesh.material.opacity]);
      }
    });
    let hit = 0;
    for (const child of tools.children) if (child.userData.hit) hit += 1;
    drawn.textContent = JSON.stringify({
      ready: true,
      webgl: renderer !== null,
      error: webglError,
      selected,
      isolated,
      view: viewIndex,
      parts,
      tools: { hit, clear: tools.children.length - hit },
    });
  }

  // ------------------------------------------------------------ selection

  function select(index) {
    selected = index;
    isolated = null;
    try {
      const here = location.pathname + location.search;
      const where = index === null ? here : "#" + encodeURIComponent(data.fasteners[index].name);
      history.replaceState(null, "", where);
    } catch (error) {
      // a page opened from disk may refuse; the hash is a convenience
    }
    status("");
    apply(true);
  }

  function isolate(index) {
    isolated = isolated === index ? null : index;
    apply(false);
  }

  function fromHash() {
    if (location.hash.length < 2) return null;
    try {
      return decodeURIComponent(location.hash.slice(1));
    } catch (error) {
      return null;
    }
  }

  const picker = new THREE.Raycaster();
  let pressed = null;
  canvas.addEventListener("pointerdown", (event) => {
    pressed = [event.clientX, event.clientY];
  });
  canvas.addEventListener("pointerup", (event) => {
    if (!pressed || !renderer) return;
    const moved = Math.hypot(event.clientX - pressed[0], event.clientY - pressed[1]);
    pressed = null;
    if (moved > 4) return;
    const rect = canvas.getBoundingClientRect();
    const at = new THREE.Vector2(
      ((event.clientX - rect.left) / rect.width) * 2 - 1,
      -((event.clientY - rect.top) / rect.height) * 2 + 1,
    );
    picker.setFromCamera(at, camera);
    const targets = partMeshes.filter((m) => m && m.visible && m.material.opacity >= OTHER_FASTENER);
    const hit = picker.intersectObjects(targets, false)[0];
    if (!hit) return;
    const part = data.parts[hit.object.userData.part];
    const owner = byName.get(part.owner ?? part.name);
    if (owner !== undefined && owner !== selected) select(owner);
    else status(part.label);
  });

  window.addEventListener("hashchange", () => {
    const wanted = fromHash();
    if (wanted !== null && byName.has(wanted)) select(byName.get(wanted));
  });

  resize();
  const wanted = fromHash() ?? data.select;
  if (wanted !== null && byName.has(wanted)) {
    selected = byName.get(wanted);
    apply(true);
  } else {
    apply(true);
    if (wanted !== null) status("No fastener named " + wanted + ".");
  }
})();
