import L from 'leaflet';

export const grayIcon = L.divIcon({
  className: 'selectable-intersection-marker',
  html: '<div style="width:8px;height:8px;background:#9ca3af;border-radius:50%;border:1px solid white;"></div>',
  iconSize: [8, 8],
  iconAnchor: [4, 4],
});

export const greenIcon = L.divIcon({
  className: 'selectable-intersection-marker',
  html: '<div style="width:18px;height:18px;background:#22c55e;border-radius:50%;border:2px solid white;box-shadow:0 1px 3px rgba(0,0,0,0.3);cursor:pointer;"></div>',
  iconSize: [18, 18],
  iconAnchor: [9, 9],
});

export const amberIcon = L.divIcon({
  className: 'selectable-intersection-marker',
  html: '<div style="width:20px;height:20px;background:#f59e0b;border-radius:50%;border:2px solid white;box-shadow:0 0 8px rgba(245,158,11,0.6);cursor:pointer;animation:pulse 2s infinite;"></div>',
  iconSize: [20, 20],
  iconAnchor: [10, 10],
});

export const purpleIcon = L.divIcon({
  className: 'selectable-intersection-marker',
  html: '<div style="width:20px;height:20px;background:#a855f7;border-radius:50%;border:2px solid white;box-shadow:0 0 8px rgba(168,85,247,0.6);cursor:pointer;"></div>',
  iconSize: [20, 20],
  iconAnchor: [10, 10],
});
