import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Play, Brain, Video, ArrowLeft, Loader2 } from 'lucide-react';
import { evaluationService } from '../services/evaluationService';
import type { ModelInfo, VideoInfo } from '../services/evaluationService';

export function EvaluatePage() {
  const navigate = useNavigate();
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [videos, setVideos] = useState<VideoInfo[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      evaluationService.listModels(),
      evaluationService.listVideos(),
    ])
      .then(([m, v]) => {
        setModels(m);
        setVideos(v);
        if (m.length > 0) setSelectedModel(m[0].path);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  const handleStart = async () => {
    setStarting(true);
    setError(null);
    try {
      const result = await evaluationService.startEvaluation(selectedModel);
      if (result.status === 'started' || result.status === 'already_running') {
        navigate('/evaluate/live');
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to start evaluation';
      setError(msg);
    } finally {
      setStarting(false);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-950 via-gray-900 to-gray-950 text-white">
      {/* Header */}
      <header className="border-b border-gray-800/50 bg-gray-900/80 backdrop-blur-sm">
        <div className="max-w-5xl mx-auto px-6 py-4 flex items-center gap-3">
          <button
            onClick={() => navigate('/')}
            className="p-2 rounded-lg hover:bg-gray-800 transition-colors"
          >
            <ArrowLeft size={18} />
          </button>
          <Brain size={20} className="text-violet-400" />
          <h1 className="text-lg font-semibold">Model Evaluation</h1>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-12">
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 size={32} className="animate-spin text-violet-400" />
          </div>
        ) : (
          <div className="space-y-8">
            {/* Model Selection */}
            <section className="bg-gray-900/60 border border-gray-800 rounded-2xl p-6">
              <div className="flex items-center gap-2 mb-4">
                <Brain size={18} className="text-violet-400" />
                <h2 className="text-base font-semibold">Select Model</h2>
              </div>

              {models.length === 0 ? (
                <p className="text-gray-500 text-sm">
                  No models found. Place <code>.pt</code> or <code>.zip</code> files in{' '}
                  <code>simulation/models/</code>
                </p>
              ) : (
                <div className="space-y-2">
                  {models.map((m) => (
                    <label
                      key={m.path}
                      className={`flex items-center justify-between p-3 rounded-xl border cursor-pointer transition-all ${
                        selectedModel === m.path
                          ? 'border-violet-500/60 bg-violet-500/10'
                          : 'border-gray-700/50 hover:border-gray-600'
                      }`}
                    >
                      <div className="flex items-center gap-3">
                        <input
                          type="radio"
                          name="model"
                          value={m.path}
                          checked={selectedModel === m.path}
                          onChange={() => setSelectedModel(m.path)}
                          className="accent-violet-500"
                        />
                        <div>
                          <p className="text-sm font-medium text-gray-200">{m.name}</p>
                          <p className="text-xs text-gray-500 mt-0.5">{m.size_mb} MB</p>
                        </div>
                      </div>
                    </label>
                  ))}
                </div>
              )}
            </section>

            {/* Video Selection */}
            <section className="bg-gray-900/60 border border-gray-800 rounded-2xl p-6">
              <div className="flex items-center gap-2 mb-4">
                <Video size={18} className="text-blue-400" />
                <h2 className="text-base font-semibold">Test Video</h2>
              </div>

              {videos.length === 0 ? (
                <p className="text-gray-500 text-sm">
                  No videos found in <code>data/traffic_video/</code>
                </p>
              ) : (
                <div className="space-y-2">
                  {videos.map((v) => (
                    <div
                      key={v.path}
                      className="flex items-center justify-between p-3 rounded-xl border border-gray-700/50 bg-gray-800/30"
                    >
                      <div className="flex items-center gap-3">
                        <Video size={16} className="text-blue-400/60" />
                        <div>
                          <p className="text-sm font-medium text-gray-200">{v.name}</p>
                          <p className="text-xs text-gray-500 mt-0.5">
                            {v.folder} · {v.size_mb} MB
                          </p>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>

            {/* Error */}
            {error && (
              <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-4 text-sm text-red-400">
                {error}
              </div>
            )}

            {/* Start button */}
            <button
              onClick={handleStart}
              disabled={starting || models.length === 0 || !selectedModel}
              className="w-full flex items-center justify-center gap-2 py-3.5 px-6 rounded-xl font-semibold text-base transition-all disabled:opacity-40 disabled:cursor-not-allowed bg-gradient-to-r from-violet-600 to-blue-600 hover:from-violet-500 hover:to-blue-500 shadow-lg shadow-violet-500/20"
            >
              {starting ? (
                <Loader2 size={20} className="animate-spin" />
              ) : (
                <Play size={20} />
              )}
              {starting ? 'Starting…' : 'Start Evaluation'}
            </button>
          </div>
        )}
      </main>
    </div>
  );
}
