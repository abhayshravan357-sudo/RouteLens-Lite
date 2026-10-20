import { useState } from 'react';
import { analyzeCaptureFile } from '../api/routing';
import type { PcapAnalysisResult, PcapHost, PcapConversation } from '../types/routing';
import './PCAPPanel.css';

const MAX_FILE_SIZE = 32 * 1024 * 1024; // 32 MB

interface PCAPPanelProps {
  onAnalysisComplete?: (result: PcapAnalysisResult) => void;
}

export default function PCAPPanel({ onAnalysisComplete }: PCAPPanelProps) {
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<PcapAnalysisResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fileSizeError, setFileSizeError] = useState(false);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = e.target.files?.[0];
    if (!selected) {
      setFile(null);
      return;
    }

    if (selected.size > MAX_FILE_SIZE) {
      setFileSizeError(true);
      setFile(null);
      e.target.value = '';
      return;
    }

    setFileSizeError(false);
    setFile(selected);
    setResult(null);
    setError(null);
  };

  const fileToBase64 = (file: File): Promise<string> => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        const result = reader.result as string;
        const base64 = result.split(',')[1];
        resolve(base64);
      };
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
  };

  const handleAnalyze = async () => {
    if (!file) return;

    setLoading(true);
    setError(null);

    try {
      const base64 = await fileToBase64(file);
      const analysis = await analyzeCaptureFile(file.name, base64);
      setResult(analysis);
      onAnalysisComplete?.(analysis);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Analysis failed';
      setError(message);
    } finally {
      setLoading(false);
    }
  };

  const handleNewFile = () => {
    setFile(null);
    setResult(null);
    setError(null);
    setFileSizeError(false);
  };

  if (loading && !result) {
    return (
      <div className="pcap-panel">
        <div className="pcap-loading">
          <span className="spinner" aria-hidden="true" />
          Analyzing capture file…
        </div>
      </div>
    );
  }

  return (
    <div className="pcap-panel">
      <div className="pcap-header">
        <h3>Capture File Analysis</h3>
        <p className="pcap-description">
          Open a local PCAP file to inspect its contents. The file is read entirely in the browser
          and only the base64-encoded bytes are sent to this app's own backend for parsing.
        </p>
      </div>

      {!result ? (
        // File picker state
        <div className="pcap-dropzone">
          <input
            type="file"
            id="pcap-file-input"
            accept=".pcap,.pcapng,.cap"
            onChange={handleFileChange}
            disabled={loading}
            aria-describedby={fileSizeError ? 'file-size-error' : 'file-hint'}
          />
          <label htmlFor="pcap-file-input" className="pcap-dropzone-label">
            <span className="pcap-dropzone-icon" aria-hidden="true">📄</span>
            <span className="pcap-dropzone-text">Choose a PCAP or PCAPNG file</span>
            <span className="pcap-dropzone-hint" id="file-hint">
              Max 32 MB. The file never leaves this browser except to your own backend.
            </span>
          </label>
          {fileSizeError && (
            <p id="file-size-error" className="pcap-error" role="alert">
              File exceeds 32 MB limit. Please choose a smaller capture.
            </p>
          )}
          {file && (
            <div className="pcap-selected-file">
              <span className="pcap-file-name">{file.name}</span>
              <span className="pcap-file-size">{(file.size / 1024).toFixed(1)} KB</span>
              <button
                type="button"
                className="btn btn-primary"
                onClick={handleAnalyze}
                disabled={loading}
              >
                {loading ? 'Analyzing…' : 'Analyze'}
              </button>
            </div>
          )}
        </div>
      ) : (
        // Results state
        <div className="pcap-results">
          {error && (
            <div className="pcap-error" role="alert">
              <span aria-hidden="true">⚠</span>
              {error}
            </div>
          )}

          {!error && result && (
            <div className="pcap-success-summary">
              <span className="pcap-success-icon" aria-hidden="true">✓</span>
              <span>
                <strong>{result.filename}</strong> — {result.format.toUpperCase()}
                {result.format === 'pcapng' && ' (detected, not yet supported)'}
              </span>
            </div>
          )}

          {result && (
            <>
              <div className="pcap-meta">
                <div className="pcap-meta-item">
                  <span className="pcap-meta-label">File size</span>
                  <span className="pcap-meta-value">{result.size_bytes} bytes</span>
                </div>
                <div className="pcap-meta-item">
                  <span className="pcap-meta-label">Analyzed</span>
                  <span className="pcap-meta-value">{new Date(result.collected_at).toLocaleString()}</span>
                </div>
                <div className="pcap-meta-item">
                  <span className="pcap-meta-label">Format</span>
                  <span className="pcap-meta-value">{result.format}</span>
                </div>
                <div className="pcap-meta-item">
                  <span className="pcap-meta-label">Parsed</span>
                  <span className={`pcap-meta-value ${result.parsed ? 'success' : 'error'}`}>
                    {result.parsed ? 'Yes' : 'No'}
                  </span>
                </div>
              </div>

              {!result.parsed && result.error && (
                <div className="pcap-error" role="alert">
                  <span aria-hidden="true">⚠</span>
                  <strong>Parse error:</strong> {result.error}
                </div>
              )}

              {result.parsed && result.summary && (
                <section className="pcap-section">
                  <h4>Summary</h4>
                  <div className="pcap-summary-grid">
                    <div className="pcap-summary-item">
                      <span className="pcap-summary-label">Total packets</span>
                      <span className="pcap-summary-value">{result.summary.total_packets}</span>
                    </div>
                    <div className="pcap-summary-item">
                      <span className="pcap-summary-label">Total bytes</span>
                      <span className="pcap-summary-value">{result.summary.total_bytes.toLocaleString()}</span>
                    </div>
                    <div className="pcap-summary-item">
                      <span className="pcap-summary-label">Duration</span>
                      <span className="pcap-summary-value">{result.summary.duration_seconds.toFixed(2)} s</span>
                    </div>
                    <div className="pcap-summary-item">
                      <span className="pcap-summary-label">Start time</span>
                      <span className="pcap-summary-value">{new Date(result.summary.start_time).toLocaleTimeString()}</span>
                    </div>
                    <div className="pcap-summary-item">
                      <span className="pcap-summary-label">End time</span>
                      <span className="pcap-summary-value">{new Date(result.summary.end_time).toLocaleTimeString()}</span>
                    </div>
                    <div className="pcap-summary-item">
                      <span className="pcap-summary-label">Link type</span>
                      <span className="pcap-summary-value">{result.summary.link_type}</span>
                    </div>
                  </div>

                  {Object.keys(result.summary.protocols).length > 0 && (
                    <div className="pcap-protocols">
                      <span className="pcap-protocols-label">Protocols:</span>
                      {Object.entries(result.summary.protocols)
                        .sort(([, a], [, b]) => b - a)
                        .map(([proto, count]) => (
                          <span key={proto} className="pcap-protocol-badge">
                            {proto.toUpperCase()}: {count}
                          </span>
                        ))}
                    </div>
                  )}
                </section>
              )}

              {result.hosts.length > 0 && (
                <section className="pcap-section">
                  <h4>Hosts ({result.hosts.length})</h4>
                  <div className="pcap-table-container">
                    <table className="pcap-table">
                      <thead>
                        <tr>
                          <th scope="col">IP Address</th>
                          <th scope="col">Packets</th>
                          <th scope="col">Bytes</th>
                          <th scope="col">First Seen</th>
                          <th scope="col">Last Seen</th>
                        </tr>
                      </thead>
                      <tbody>
                        {result.hosts.map((host: PcapHost, i) => (
                          <tr key={i}>
                            <td className="mono">{host.ip}</td>
                            <td>{host.packets}</td>
                            <td>{host.bytes.toLocaleString()}</td>
                            <td>{new Date(host.first_seen).toLocaleTimeString()}</td>
                            <td>{new Date(host.last_seen).toLocaleTimeString()}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              )}

              {result.conversations.length > 0 && (
                <section className="pcap-section">
                  <h4>Conversations ({result.conversations.length})</h4>
                  <div className="pcap-table-container">
                    <table className="pcap-table">
                      <thead>
                        <tr>
                          <th scope="col">Source</th>
                          <th scope="col">Destination</th>
                          <th scope="col">Protocol</th>
                          <th scope="col">Packets</th>
                          <th scope="col">Bytes</th>
                        </tr>
                      </thead>
                      <tbody>
                        {result.conversations.map((conv: PcapConversation, i) => (
                          <tr key={i}>
                            <td className="mono">{conv.src}</td>
                            <td className="mono">{conv.dst}</td>
                            <td><span className="pcap-protocol-badge">{conv.protocol.toUpperCase()}</span></td>
                            <td>{conv.packets}</td>
                            <td>{conv.bytes.toLocaleString()}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              )}

              {result.limitations.length > 0 && (
                <section className="pcap-section">
                  <h4>Limitations</h4>
                  <ul className="pcap-limitations">
                    {result.limitations.map((lim, i) => (
                      <li key={i}>{lim}</li>
                    ))}
                  </ul>
                </section>
              )}

              {!result.parsed && result.hosts.length === 0 && result.conversations.length === 0 && (
                <p className="pcap-empty">No host or conversation data available.</p>
              )}
            </>
          )}

          <div className="pcap-actions">
            <button type="button" className="btn btn-secondary" onClick={handleNewFile}>
              Analyze Another File
            </button>
          </div>
        </div>
      )}
    </div>
  );
}