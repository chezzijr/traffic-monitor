import { Camera } from 'lucide-react';

export function CameraPanel() {
  return (
    <div className="bg-white rounded-lg shadow p-4">
      <div className="flex items-center gap-2 mb-3">
        <Camera size={20} />
        <h3 className="text-lg font-semibold">Camera Feed</h3>
      </div>
      <div className="aspect-video bg-gray-100 rounded flex items-center justify-center text-gray-400">
        <p>Camera feed placeholder</p>
      </div>
    </div>
  );
}
