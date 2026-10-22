import { useState } from 'react';
import { analyzeCaptureFile } from '../api/routing';
import type {
  PcapAnalysisResult,
  PcapHost,
  PcapConversation,
  PcapPacketDetail,
  PcapHandshake,
} from '../types/routing';
import './PCAPPanel.css';

const MAX_FILE_SIZE = 32 * 1024 * 1024; // 32 MB

interface PCAPPanelProps {
  onAnalysisComplete?: (result: PcapAnalysisResult) => void;
}

/**
 * The protocol-specific facts a packet carries, in the order a reader
 * would want them. Only the ones the packet actually has are shown.
 */
function packetFacts(packet: PcapPacketDetail): { label: string; value: string }[] {
  const facts: { label: string; value: string }[] = [];

  if (packet.protocol) facts.push({ label: 'Protocol', value: packet.protocol });
  if (packet.src_ip) facts.push({ label: 'Source', value: packet.src_ip });
  if (packet.dst_ip) facts.push({ label: 'Destination', value: packet.dst_ip });
  if (packet.src_port !== null && packet.dst_port !== null) {
    facts.push({
      label: 'Ports',
      value: `${packet.src_port} → ${packet.dst_port}`,
    });
  }
  if (packet.tcp_flags.length > 0) {
    facts.push({ label: 'TCP flags', value: packet.tcp_flags.join(', ') });
  }
  if (packet.icmp_type_name) {
    facts.push({
      label: 'ICMP type',
      value:
        packet.icmp_code_name !== null
          ? `${packet.icmp_type_name} (${packet.icmp_type} / ${packet.icmp_code_name})`
          : `${packet.icmp_type_name} (${packet.icmp_type})`,
    });
  }
  if (packet.dns_query_name) {
    facts.push({
      label: 'DNS query',
      value: packet.dns_query_name,
    });
  }
  if (packet.dns_answers.length > 0) {
    facts.push({ label: 'DNS answers', value: packet.dns_answers.join(', ') });
  }
  if (packet.arp_operation_name) {
    facts.push({
      label: 'ARP operation',
      value: packet.arp_operation_name,
    });
  }
  if (packet.handshake_stage) {
    facts.push({ label: 'Handshake stage', value: packet.handshake_stage });
  }
  if (packet.src_mac) facts.push({ label: 'Source MAC', value: packet.src_mac });
  if (packet.dst_mac) facts.push({ label: 'Destination MAC', value: packet.dst_mac });
  if (packet.ethertype) facts.push({ label: 'Ethertype', value: packet.ethertype });

  return facts;
}

function HandshakeCard({ handshake }: { handshake: PcapHandshake }) {
  return (
    <div className={`pcap-handshake ${handshake.complete ? 'complete' : 'partial'}`}>
      <div className="pcap-handshake-head">
        <span className="pcap-handshake-pair mono">
          {handshake.client} ↔ {handshake.server}
        </span>
        <span className="pcap-handshake-badge">
          {handshake.complete ? 'Complete' : 'Partial'}
        </span>
      </div>
      {handshake.stages.length > 0 && (
        <ol className="pcap-handshake-stages">
          {handshake.stages.map((stage, i) => (
            <li key={i} className="mono">
              {stage}
            </li>
          ))}
        </ol>
      )}
      <p className="pcap-handshake-explanation">{handshake.explanation}</p>
    </div>
  );
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

              {result.handshakes && result.handshakes.length > 0 && (
                <section className="pcap-section">
                  <h4>Handshakes ({result.handshakes.length})</h4>
                  <div className="pcap-handshake-list">
                    {result.handshakes.map((handshake, i) => (
                      <HandshakeCard key={i} handshake={handshake} />
                    ))}
                  </div>
                </section>
              )}

              {result.packets && result.packets.length > 0 && (
                <section className="pcap-section">
                  <h4>
                    Packets ({result.packets.length})
                    <span className="pcap-section-hint">
                      what each packet actually carried
                    </span>
                  </h4>
                  <div className="pcap-packet-list">
                    {result.packets.map((packet) => (
                      <details
                        key={packet.index}
                        className={`pcap-packet ${packet.parsed ? '' : 'unparsed'}`}
                      >
                        <summary>
                          <span className="pcap-packet-index mono">
                            #{packet.index}
                          </span>
                          <span className="pcap-packet-flow mono">
                            {packet.src_ip ?? packet.src_mac ?? '?'} →{' '}
                            {packet.dst_ip ?? packet.dst_mac ?? '?'}
                          </span>
                          {packet.protocol && (
                            <span className="pcap-packet-protocol">
                              {packet.protocol}
                            </span>
                          )}
                          <span className="pcap-packet-time mono">
                            {new Date(packet.timestamp).toLocaleTimeString()}
                          </span>
                        </summary>

                        <div className="pcap-packet-facts">
                          {packetFacts(packet).map((fact) => (
                            <div className="pcap-packet-fact" key={fact.label}>
                              <span className="detail-label">{fact.label}</span>
                              <span className="detail-value mono">
                                {fact.value}
                              </span>
                            </div>
                          ))}
                        </div>

                        {packet.notes.length > 0 && (
                          <ul className="pcap-packet-notes">
                            {packet.notes.map((note, i) => (
                              <li key={i}>{note}</li>
                            ))}
                          </ul>
                        )}
                      </details>
                    ))}
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