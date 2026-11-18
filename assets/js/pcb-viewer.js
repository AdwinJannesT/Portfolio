// Hero PCB: the board's real 3D model (converted from its KiCad STEP export) on a transparent
// WebGL canvas. Each separately modelled part sits at its true STEP position when assembled;
// set(e) moves the parts between their exploded offsets (e = 0) and the assembled board (e = 1).
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

const smooth = t => t * t * (3 - 2 * t);
const clamp01 = t => Math.min(1, Math.max(0, t));

export async function createPcbViewer(stage, url, initial = 1) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'low-power' });
  renderer.setClearColor(0x000000, 0);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.NeutralToneMapping;
  renderer.toneMappingExposure = 1.05;
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
  const canvas = renderer.domElement;
  canvas.setAttribute('aria-hidden', 'true');

  const scene = new THREE.Scene();
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  pmrem.dispose();
  const key = new THREE.DirectionalLight(0xffffff, 1.6);
  key.position.set(-0.6, 1, 0.45);
  scene.add(key);

  const gltf = await new GLTFLoader().loadAsync(url);
  const model = gltf.scene;
  scene.add(model);

  // parts that carry an exploded offset (glTF node extras -> userData)
  const parts = [];
  model.traverse(o => {
    const x = o.userData && o.userData.explode;
    if (!x) return;
    const nested = typeof o.userData.order !== 'number';
    parts.push({
      obj: o,
      base: o.position.clone(),
      off: new THREE.Vector3(x[0], x[1], x[2]),
      // stagger: parts settle left to right; a part's own sub-part settles last
      start: nested ? 0.4 : 0.35 * o.userData.order
    });
  });

  // isometric view
  const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, -1000, 1000);
  const dir = new THREE.Vector3(1, 1, 1).normalize();
  camera.up.set(0, 1, 0);
  camera.position.copy(dir);
  camera.lookAt(0, 0, 0);
  camera.updateMatrixWorld();
  const view = camera.matrixWorldInverse.clone();

  function pose(e) {
    for (const p of parts) {
      const t = smooth(clamp01((e - p.start) / 0.6));
      p.obj.position.copy(p.base).addScaledVector(p.off, 1 - t);
    }
    model.updateMatrixWorld(true);
  }

  // framing (view-space box) for the exploded and the assembled pose
  const corner = new THREE.Vector3();
  function frame(e) {
    pose(e);
    const lo = new THREE.Vector3(Infinity, Infinity, Infinity), hi = lo.clone().negate();
    model.traverse(o => {
      if (!o.isMesh) return;
      const g = o.geometry;
      if (!g.boundingBox) g.computeBoundingBox();
      const b = g.boundingBox;
      for (let i = 0; i < 8; i++) {
        corner.set(i & 1 ? b.max.x : b.min.x, i & 2 ? b.max.y : b.min.y, i & 4 ? b.max.z : b.min.z)
          .applyMatrix4(o.matrixWorld).applyMatrix4(view);
        lo.min(corner); hi.max(corner);
      }
    });
    return { cx: (lo.x + hi.x) / 2, cy: (lo.y + hi.y) / 2, w: hi.x - lo.x, h: hi.y - lo.y };
  }
  const f0 = frame(0), f1 = frame(1);

  let current = clamp01(initial), w = 0, h = 0, raf = 0;
  function draw() {
    raf = 0;
    if (!w || !h) return;
    const e = current;
    pose(e);
    const lerp = (a, b) => a + (b - a) * e;
    const cx = lerp(f0.cx, f1.cx), cy = lerp(f0.cy, f1.cy);
    const bw = lerp(f0.w, f1.w), bh = lerp(f0.h, f1.h);
    const aspect = w / h, pad = 1.08;
    let halfH = Math.max(bh, bw / aspect) * pad / 2;
    const halfW = halfH * aspect;
    // shift the frustum instead of the camera so the view direction stays isometric
    camera.left = cx - halfW; camera.right = cx + halfW;
    camera.top = cy + halfH; camera.bottom = cy - halfH;
    camera.updateProjectionMatrix();
    renderer.render(scene, camera);
  }
  const request = () => { if (!raf) raf = requestAnimationFrame(draw); };

  function resize() {
    const r = stage.getBoundingClientRect();
    w = Math.round(r.width); h = Math.round(r.height);
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    request();
  }
  new ResizeObserver(resize).observe(stage);
  canvas.addEventListener('webglcontextrestored', request);

  stage.appendChild(canvas);
  resize();
  draw();

  return {
    set(e) {
      e = clamp01(e);
      if (e === current) return;
      current = e;
      request();
    }
  };
}
