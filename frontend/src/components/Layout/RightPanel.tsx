import { X } from 'lucide-react';
import type { ReactNode } from 'react';

interface RightPanelProps {
  isOpen: boolean;
  onClose: () => void;
  children: ReactNode;
}

export function RightPanel({ isOpen, onClose, children }: RightPanelProps) {
  return (
    <>
      {/* Backdrop */}
      {isOpen && (
        <div
          className="fixed inset-0 bg-black/20 z-[1200]"
          onClick={onClose}
        />
      )}
      {/* Panel */}
      <div
        className={`fixed top-0 right-0 h-full w-96 bg-white shadow-2xl z-[1300] transition-transform duration-300 ease-in-out ${
          isOpen ? 'translate-x-0' : 'translate-x-full'
        }`}
      >
        <div className="relative h-full flex flex-col">
          <button
            onClick={onClose}
            className="absolute top-3 right-3 p-1 rounded-full hover:bg-gray-100 text-gray-500 hover:text-gray-700 transition-colors z-10"
            title="Close"
          >
            <X size={16} />
          </button>
          <div className="flex-1 overflow-auto">
            {children}
          </div>
        </div>
      </div>
    </>
  );
}
