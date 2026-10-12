const SHELL="digest-shell-v2",FILES=["./","index.html","icon.svg"];
self.addEventListener("install",e=>e.waitUntil(caches.open(SHELL).then(c=>c.addAll(FILES))));
self.addEventListener("activate",e=>e.waitUntil(caches.keys().then(k=>Promise.all(k.filter(x=>x!==SHELL).map(x=>caches.delete(x))))));
// Network first, so you always get the newest digest; cache is the offline fallback.
self.addEventListener("fetch",e=>{
  if(e.request.method!=="GET")return;
  e.respondWith(fetch(e.request).then(r=>{const c=r.clone();caches.open(SHELL).then(x=>x.put(e.request,c));return r}).catch(()=>caches.match(e.request)));
});
