import * as THREE from "./three.module.min.js";
import { GLTFLoader } from "./GLTFLoader.js";
import { OrbitControls } from "./OrbitControls.js";

const MODEL_URL = (() => {
  const url = new URL("./archive-cassette.glb", import.meta.url);
  const assetToken = new URL(import.meta.url).searchParams.get("asset_token");
  if (assetToken) url.searchParams.set("asset_token", assetToken);
  return url.href;
})();
const ASSEMBLY_MODEL_URL = (() => {
  const url = new URL("./archive-assembly.glb", import.meta.url);
  const assetToken = new URL(import.meta.url).searchParams.get("asset_token");
  if (assetToken) url.searchParams.set("asset_token", assetToken);
  return url.href;
})();
let modelPromise;
let assemblyModelPromise;

function loadModel() {
  if (!modelPromise) modelPromise = new GLTFLoader().loadAsync(MODEL_URL);
  return modelPromise;
}

function loadAssemblyModel() {
  if (!assemblyModelPromise) assemblyModelPromise = new GLTFLoader().loadAsync(ASSEMBLY_MODEL_URL);
  return assemblyModelPromise;
}

function cloneMaterials(root) {
  root.traverse((object) => {
    if (!object.isMesh) return;
    object.castShadow = true;
    object.receiveShadow = true;
    if (Array.isArray(object.material)) object.material = object.material.map((material) => material.clone());
    else if (object.material) object.material = object.material.clone();
  });
}

export async function mountArchiveScene(root) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.45));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.08;
  renderer.domElement.setAttribute("aria-label", "三维记忆档案阵列，可拖动旋转和滚轮缩放");
  root.replaceChildren(renderer.domElement);

  const scene = new THREE.Scene();
  scene.fog = new THREE.Fog("#e8e5e1", 14, 30);
  const camera = new THREE.PerspectiveCamera(31, 1, 0.1, 80);
  camera.position.set(8.8, 5.8, 14.5);
  camera.lookAt(0, -0.6, 0);
  scene.add(new THREE.HemisphereLight("#fffaf1", "#8f8878", 2.2));
  const key = new THREE.DirectionalLight("#fff8ea", 3.3);
  key.position.set(7, 12, 8);
  key.castShadow = true;
  scene.add(key);
  const fill = new THREE.DirectionalLight("#d6ded4", 1.1);
  fill.position.set(-8, 3, -6);
  scene.add(fill);
  const floor = new THREE.Mesh(
    new THREE.PlaneGeometry(44, 26),
    new THREE.MeshStandardMaterial({ color: "#d6cbbc", roughness: 0.92 }),
  );
  floor.rotation.x = -Math.PI / 2;
  floor.position.y = -2.45;
  floor.receiveShadow = true;
  scene.add(floor);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.075;
  controls.enablePan = true;
  controls.panSpeed = 0.35;
  controls.minDistance = 8;
  controls.maxDistance = 24;
  controls.target.set(0, -0.65, 0);

  let source;
  try {
    const gltf = await loadModel();
    source = gltf.scene;
    const bounds = new THREE.Box3().setFromObject(source);
    const size = bounds.getSize(new THREE.Vector3());
    const scale = 2.35 / Math.max(size.y, 0.001);
    source.scale.setScalar(scale);
    source.updateMatrixWorld(true);
  } catch (error) {
    renderer.dispose();
    root.innerHTML = '<span class="scene-loading">ARCHIVE SCENE / UNAVAILABLE</span>';
    return;
  }

  const group = new THREE.Group();
  scene.add(group);
  const columns = 5;
  const rows = 3;
  const spacingX = 2.25;
  const spacingZ = 1.65;
  const copies = [];
  for (let column = 0; column < columns; column += 1) {
    for (let row = 0; row < rows; row += 1) {
      const clone = source.clone(true);
      cloneMaterials(clone);
      clone.position.set((column - 2) * spacingX, -1.2 + (row % 2) * 0.03, (row - 1) * spacingZ);
      clone.rotation.y = -0.18;
      group.add(clone);
      copies.push({ object: clone, column, row, index: column * rows + row });
    }
  }

  let frame = 0;
  let disposed = false;
  const resize = () => {
    if (!root.isConnected) {
      disposed = true;
      cancelAnimationFrame(frame);
      controls.dispose();
      renderer.dispose();
      return;
    }
    const width = Math.max(root.clientWidth, 320);
    const height = Math.max(root.clientHeight, 240);
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  };
  const animate = (time) => {
    if (disposed) return;
    resize();
    const selected = Number(root.dataset.selectedIndex || 0);
    copies.forEach((item) => {
      const focus = item.index === selected % copies.length;
      const wave = Math.sin(time * 0.0015 + item.column * 0.75 + item.row * 0.45) * 0.055;
      const targetY = -1.2 + wave + (focus ? 0.48 : 0);
      item.object.position.y += (targetY - item.object.position.y) * 0.08;
      item.object.rotation.y += ((focus ? -0.05 : -0.18) - item.object.rotation.y) * 0.06;
    });
    group.rotation.y += 0.0007;
    controls.update();
    renderer.render(scene, camera);
    frame = requestAnimationFrame(animate);
  };
  resize();
  frame = requestAnimationFrame(animate);
}

const ASSEMBLY_PARTS = [
  ["fasteners", "紧固件", 2.75],
  ["cover", "透明盖板", 1.85],
  ["optical-lenses", "折射环组", 0.75],
  ["optical-core", "光学核心", -0.15],
  ["substrate", "信息基板", -1.1],
  ["carrier", "背板与框架", -2.05],
];

function disposeObject(root) {
  root.traverse((object) => {
    if (!object.isMesh) return;
    object.geometry?.dispose?.();
    const materials = Array.isArray(object.material) ? object.material : [object.material];
    materials.forEach((material) => {
      if (!material) return;
      Object.values(material).forEach((value) => value?.isTexture && value.dispose());
      material.dispose?.();
    });
  });
}

export async function mountAssemblyViewer(root, hooks = {}) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  renderer.domElement.tabIndex = 0;
  renderer.domElement.setAttribute("aria-label", "档案三维模型，可拖动旋转、方向键平移和滚轮缩放");
  root.replaceChildren(renderer.domElement);
  const scene = new THREE.Scene();
  scene.background = new THREE.Color("#eae5e1");
  scene.fog = new THREE.Fog("#eae5e1", 13.5, 26.5);
  scene.add(new THREE.HemisphereLight("#fffaf1", "#8f8878", 2.2));
  const key = new THREE.DirectionalLight("#fff8ea", 3.2);
  key.position.set(7, 12, 8);
  scene.add(key);
  const fill = new THREE.DirectionalLight("#d6ded4", 1.15);
  fill.position.set(-8, 3, -6);
  scene.add(fill);
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(44, 26), new THREE.MeshStandardMaterial({ color: "#d6cbbc", roughness: 0.92 }));
  floor.rotation.x = -Math.PI / 2;
  floor.position.y = -3.45;
  scene.add(floor);
  const camera = new THREE.PerspectiveCamera(34, 1, 0.3, 120);
  camera.position.set(7.2, 3.8, 12);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.085;
  controls.rotateSpeed = 0.65;
  controls.zoomSpeed = 0.7;
  controls.panSpeed = 0.7;
  controls.minDistance = 5;
  controls.maxDistance = 28;
  controls.maxTargetRadius = 5;
  controls.screenSpacePanning = true;
  controls.target.set(0, 0, 0);
  controls.update();

  let frame = 0;
  let disposed = false;
  let spread = 0;
  let targetSpread = 0;
  let groups = new Map();
  const setState = (value) => hooks.onState?.(value);
  const setError = (error) => {
    const detail = error?.message ? " / " + String(error.message).slice(0, 100) : "";
    root.innerHTML = '<span class="scene-loading">MODEL LOAD FAILED' + detail.replace(/[<>]/g, "") + "</span>";
    hooks.onError?.(error);
  };
  try {
    const gltf = await loadAssemblyModel();
    if (!root.isConnected) throw new Error("查看器已关闭");
    const source = gltf.scene;
    const bounds = new THREE.Box3().setFromObject(source);
    const size = bounds.getSize(new THREE.Vector3());
    source.scale.setScalar(3.15 / Math.max(size.y, 0.001));
    source.position.set(0, -1.85, 0);
    for (const [id] of ASSEMBLY_PARTS) {
      const group = new THREE.Group();
      group.name = id;
      groups.set(id, group);
      source.add(group);
    }
    const meshes = [];
    source.traverse((object) => { if (object.isMesh) meshes.push(object); });
    meshes.forEach((mesh) => {
      const id = mesh.userData?.assemblyPart || "cover";
      groups.get(id)?.add(mesh);
    });
    groups.forEach((group) => cloneMaterials(group));
    scene.add(source);
    const resize = () => {
      if (!root.isConnected) {
        disposed = true;
        cancelAnimationFrame(frame);
        controls.dispose();
        disposeObject(source);
        renderer.dispose();
        return;
      }
      const width = Math.max(root.clientWidth, 320);
      const height = Math.max(root.clientHeight, 240);
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    };
    const animate = (time) => {
      if (disposed) return;
      resize();
      spread += (targetSpread - spread) * 0.075;
      ASSEMBLY_PARTS.forEach(([id, , depth]) => groups.get(id).position.z = depth * spread);
      controls.update();
      renderer.render(scene, camera);
      frame = requestAnimationFrame(animate);
    };
    resize();
    frame = requestAnimationFrame(animate);
    const api = {
      setExploded(value) { targetSpread = value ? 1 : 0; setState(value ? "正在拆解" : spread > 0.01 ? "正在重组" : "已组装"); },
      reset() { controls.target.set(0, 0, 0); camera.position.set(7.2, 3.8, 12); controls.update(); },
      dispose() { if (disposed) return; disposed = true; cancelAnimationFrame(frame); controls.dispose(); scene.remove(source); disposeObject(source); renderer.dispose(); },
    };
    setState("已组装");
    return api;
  } catch (error) {
    if (!disposed) {
      disposed = true;
      controls.dispose();
      renderer.dispose();
      setError(error);
    }
    return null;
  }
}

window.MemoryCinema3D = { mountArchiveScene, mountAssemblyViewer };
window.dispatchEvent(new Event("memory-cinema-ready"));
