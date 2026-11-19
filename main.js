const COLORS={"Pending":"#DC2626","In Progress":"#2563EB","Resolved":"#16A34A"};
function pin(c){return L.divIcon({className:"",html:`<div style="width:22px;height:22px;border-radius:50% 50% 50% 0;background:${c};transform:rotate(-45deg);border:3px solid #fff;box-shadow:0 3px 8px #0008"></div>`,iconSize:[22,22],iconAnchor:[11,22]})}
function baseMap(id,c=[12.9716,77.5946],z=12){const m=L.map(id).setView(c,z);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",{attribution:"© OpenStreetMap"}).addTo(m);return m}
async function loadMarkers(map,status){
 const data=await (await fetch("/api/reports")).json();const pts=[];
 data.filter(r=>!status||r.status===status).forEach(r=>{
  const img=r.photo?`<img src="/static/uploads/${r.photo}" style="width:100%;border-radius:8px;margin:6px 0">`:"";
  L.marker([r.lat,r.lng],{icon:pin(COLORS[r.status])}).addTo(map).bindPopup(
   `<b>#${r.id} ${r.issue_type}</b><br><small>${r.address||""}</small>${img}<p style="margin:4px 0">${r.description}</p><b style="color:${COLORS[r.status]}">${r.status}</b>`);
  pts.push([r.lat,r.lng])});
 if(pts.length)map.fitBounds(pts,{padding:[40,40],maxZoom:15})}
function initPicker(){
 const map=baseMap("pickmap");let mk;
 function set(lat,lng){if(mk)map.removeLayer(mk);mk=L.marker([lat,lng],{icon:pin("#F97316")}).addTo(map);
  document.getElementById("lat").value=lat.toFixed(6);document.getElementById("lng").value=lng.toFixed(6);
  document.getElementById("coords").textContent=lat.toFixed(5)+", "+lng.toFixed(5)}
 map.on("click",e=>set(e.latlng.lat,e.latlng.lng));
 document.getElementById("gps").onclick=()=>navigator.geolocation?.getCurrentPosition(p=>{map.setView([p.coords.latitude,p.coords.longitude],17);set(p.coords.latitude,p.coords.longitude)},()=>alert("Could not get location. Click the map instead."));
 document.getElementById("photo").onchange=e=>{const f=e.target.files[0];if(f){const p=document.getElementById("preview");p.src=URL.createObjectURL(f);p.classList.remove("d-none")}}}
