(() => {
  'use strict';
  const loads = new Map();
  let mathQueue = Promise.resolve();

  function load(name, local, fallback) {
    if (loads.has(name)) return loads.get(name);
    const promise = new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.async = true;
      script.onload = resolve;
      script.onerror = () => {
        if (script.src.startsWith(location.origin)) {
          script.src = fallback;
        } else {
          script.remove();
          reject(new Error(`${name} could not be loaded`));
        }
      };
      script.src = local;
      document.head.appendChild(script);
    }).catch(error => { loads.delete(name); throw error; });
    loads.set(name, promise);
    return promise;
  }

  async function ensureMermaid() {
    if (!window.mermaid?.render) {
      await load('Mermaid', '/vendor/mermaid.min.js', 'https://unpkg.com/mermaid@11.4.1/dist/mermaid.min.js');
    }
    return window.mermaid;
  }

  async function renderMath(nodes) {
    let elements = [...nodes].filter(node => node?.isConnected && /\$|\\\(|\\\[/.test(node.textContent || ''));
    if (!elements.length) return;
    if (!window.MathJax?.typesetPromise) {
      window.MathJax = window.MathJax || {};
      window.MathJax.startup = {...window.MathJax.startup, typeset: false};
      await load('MathJax', '/vendor/mathjax-tex-svg.js', 'https://cdnjs.cloudflare.com/ajax/libs/mathjax/3.2.2/es5/tex-svg.min.js');
    }
    await window.MathJax.startup?.promise;
    mathQueue = mathQueue.catch(() => {}).then(async () => {
      elements = elements.filter(node => node.isConnected);
      if (!elements.length) return;
      window.MathJax.typesetClear?.(elements);
      await window.MathJax.typesetPromise(elements);
    });
    return mathQueue;
  }

  window.ERWRenderLibraries = {ensureMermaid, renderMath};
})();
