import * as THREE from 'three';
import {SparkRenderer, SplatMesh} from '@sparkjsdev/spark';

const status = document.querySelector('#status');

try {
  const testCase = JSON.parse(decodeURIComponent(location.hash.slice(1)));
  if (!Array.isArray(testCase.matrix) || testCase.matrix.length !== 16 ||
      !testCase.matrix.every(Number.isFinite) || typeof testCase.scene !== 'string') {
    throw Error('Invalid case');
  }

  const renderer = new THREE.WebGLRenderer({antialias: false, alpha: true});
  renderer.setPixelRatio(1);
  renderer.setSize(512, 512);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  document.body.prepend(renderer.domElement);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x000000);
  const camera = new THREE.PerspectiveCamera(55, 1, 0.1, 1000);
  camera.matrixAutoUpdate = false;
  camera.matrix.fromArray(new THREE.Matrix4().set(...testCase.matrix).elements);
  camera.matrixWorld.copy(camera.matrix);
  camera.matrixWorldInverse.copy(camera.matrix).invert();
  camera.updateProjectionMatrix();

  const spark = new SparkRenderer({renderer, onDirty: () => {}});
  scene.add(spark);
  const mesh = new SplatMesh({
    url: '/api/splat.ply?scene=' + encodeURIComponent(testCase.scene),
    fileName: 'splat.ply',
  });
  await mesh.initialized;
  scene.add(mesh);

  let frames = 0;
  function draw() {
    renderer.render(scene, camera);
    if (++frames < 180) {
      requestAnimationFrame(draw);
    } else {
      const count = mesh.packedSplats?.numSplats ?? mesh.extSplats?.numSplats ?? 0;
      status.textContent = `Ready · ${count} splats · ${frames} frames`;
    }
  }
  draw();
} catch (error) {
  status.textContent = 'Error: ' + (error.message || error);
}
