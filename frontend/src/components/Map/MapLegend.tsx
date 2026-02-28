interface MapLegendProps {
  className?: string;
}

export function MapLegend({ className = '' }: MapLegendProps) {
  return (
    <div
      className={`bg-white rounded-lg shadow-md p-3 ${className}`}
      style={{ zIndex: 1000 }}
    >
      <h4 className="text-sm font-semibold text-gray-700 mb-2">Legend</h4>
      <div className="space-y-2">
        {/* Regular intersection */}
        <div className="flex items-center gap-2">
          <div className="w-4 h-4 bg-blue-500 rounded-full border-2 border-white shadow-sm" />
          <span className="text-xs text-gray-600">Regular Intersection</span>
        </div>
        {/* Traffic light intersection */}
        <div className="flex items-center gap-2">
          <div className="w-5 h-5 bg-green-500 rounded-full border-2 border-white shadow-sm flex items-center justify-center">
            <svg
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 24 24"
              fill="white"
              className="w-3 h-3"
            >
              <rect x="9" y="2" width="6" height="20" rx="1" />
              <circle cx="12" cy="6" r="2" />
              <circle cx="12" cy="12" r="2" />
              <circle cx="12" cy="18" r="2" />
            </svg>
          </div>
          <span className="text-xs text-gray-600">Traffic Light</span>
        </div>
        {/* OSM traffic light */}
        <div className="flex items-center gap-2">
          <div className="w-4 h-4 bg-orange-500 rounded-full border-2 border-white shadow-sm" />
          <span className="text-xs text-gray-600">OSM Traffic Light</span>
        </div>
      </div>
    </div>
  );
}
