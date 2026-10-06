// The three.js names the HTML view uses, and so the only ones the vendored bundle
// keeps: esbuild shakes out the rest. scripts/vendor_three.py bundles this file;
// tests/test_view.py checks that every THREE.<name> in viewer.js is listed here.
export {
  Box3,
  BufferAttribute,
  BufferGeometry,
  Color,
  DirectionalLight,
  DoubleSide,
  EdgesGeometry,
  Group,
  HemisphereLight,
  LineBasicMaterial,
  LineSegments,
  Mesh,
  MeshLambertMaterial,
  PerspectiveCamera,
  Raycaster,
  Scene,
  Sphere,
  Vector2,
  Vector3,
  WebGLRenderer,
} from 'three';
export { OrbitControls } from 'three/addons/controls/OrbitControls.js';
