import { AlertTriangle } from 'lucide-react';

interface SwapConfirmDialogProps {
  isOpen: boolean;
  isLoading?: boolean;
  currentModelId: string | null;
  currentTlIds: string[];
  nextModelId: string;
  onCancel: () => void;
  onConfirm: () => void;
}

/**
 * Pre-deploy confirmation when an active deployment already exists.
 *
 * Digital Twin is singleton-only — a new deploy stops the current one. This
 * dialog gives the user an explicit chance to abort before that swap happens.
 */
export function SwapConfirmDialog({
  isOpen,
  isLoading = false,
  currentModelId,
  currentTlIds,
  nextModelId,
  onCancel,
  onConfirm,
}: SwapConfirmDialogProps) {
  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-[3000]"
      onClick={onCancel}
    >
      <div
        className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4 p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start gap-3 mb-4">
          <AlertTriangle className="text-amber-500 flex-shrink-0 mt-0.5" size={22} />
          <div>
            <h3 className="text-base font-semibold text-gray-900">
              Swap active deployment?
            </h3>
            <p className="text-sm text-gray-600 mt-1">
              A deploy is already running. Starting a new one will stop the
              current model.
            </p>
          </div>
        </div>

        <div className="bg-gray-50 rounded p-3 text-xs text-gray-700 space-y-1 mb-4">
          <div className="flex gap-2">
            <span className="font-medium text-gray-500 w-16 shrink-0">Current:</span>
            <span className="font-mono text-gray-800 break-all">
              {currentModelId || '(unknown)'}
            </span>
          </div>
          <div className="flex gap-2">
            <span className="font-medium text-gray-500 w-16 shrink-0">TLs:</span>
            <span className="font-mono text-gray-800">
              {currentTlIds.length === 0
                ? '(none)'
                : currentTlIds.length <= 3
                  ? currentTlIds.join(', ')
                  : `${currentTlIds.slice(0, 3).join(', ')} + ${currentTlIds.length - 3} more`}
            </span>
          </div>
          <div className="flex gap-2">
            <span className="font-medium text-gray-500 w-16 shrink-0">Next:</span>
            <span className="font-mono text-gray-800 break-all">{nextModelId}</span>
          </div>
        </div>

        <div className="flex justify-end gap-2">
          <button
            onClick={onCancel}
            disabled={isLoading}
            className="px-4 py-1.5 text-sm rounded border border-gray-300 text-gray-700 hover:bg-gray-50 transition-colors disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            disabled={isLoading}
            className="px-4 py-1.5 text-sm rounded bg-amber-600 text-white hover:bg-amber-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isLoading ? 'Swapping…' : 'Swap deploy'}
          </button>
        </div>
      </div>
    </div>
  );
}
