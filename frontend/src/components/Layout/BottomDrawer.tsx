import { X } from 'lucide-react';
import type { ReactNode } from 'react';

interface BottomDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  children: ReactNode;
}

export function BottomDrawer({ isOpen, onClose, children }: BottomDrawerProps) {
  return (
    <div
      className={`absolute bottom-0 left-0 right-0 bg-white border-t border-gray-200 shadow-2xl z-[1100] transition-transform duration-300 ease-in-out ${
        isOpen ? 'translate-y-0' : 'translate-y-full'
      }`}
      style={{ height: '40%' }}
    >
      <div className="relative h-full flex flex-col">
        <button
          onClick={onClose}
          className="absolute top-2 right-2 p-1 rounded-full hover:bg-gray-100 text-gray-500 hover:text-gray-700 transition-colors z-10"
          title="Close"
        >
          <X size={16} />
        </button>
        <div className="flex-1 overflow-auto p-4">
          {children}
        </div>
      </div>
    </div>
  );
}
