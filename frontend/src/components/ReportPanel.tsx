/**
 * ReportPanel
 *
 * Lets the student take away what was actually measured.
 *
 * The report is not a screenshot. It lists the evidence behind each
 * claim, where it came from, when it was collected, what was
 * simulated, and what could not be established. The limitations are
 * part of the report rather than a footnote.
 */

import { useState } from 'react';
import { fetchReportMarkdown } from '../api/routing';
import './ReportPanel.css';

export default function ReportPanel() {
  const [building, setBuilding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<string | null>(null);

  const handleBuild = async () => {
    setBuilding(true);
    setError(null);
    try {
      const markdown = await fetchReportMarkdown();
      setReport(markdown);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not build the report');
    } finally {
      setBuilding(false);
    }
  };

  const handleDownload = () => {
    if (!report) return;
    const blob = new Blob([report], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'routelens-report.md';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const handleCopy = async () => {
    if (!report) return;
    try {
      await navigator.clipboard.writeText(report);
      setError(null);
    } catch {
      setError('Could not copy to the clipboard. Select the text and copy it instead.');
    }
  };

  return (
    <div className="report-panel">
      <div className="report-panel-header">
        <div>
          <h3>Take away what you found</h3>
          <p className="report-panel-intro">
            Build a report of what was actually measured on this machine,
            with the source and time for every claim, what was simulated
            instead, and what could not be established.
          </p>
        </div>
        <div className="report-panel-actions">
          <button
            type="button"
            className="btn btn-secondary"
            onClick={handleBuild}
            disabled={building}
          >
            {building ? 'Building…' : 'Build report'}
          </button>
          {report && (
            <>
              <button
                type="button"
                className="btn btn-primary"
                onClick={handleDownload}
              >
                Download .md
              </button>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={handleCopy}
              >
                Copy
              </button>
            </>
          )}
        </div>
      </div>

      {error && (
        <div className="error-message" role="alert">
          <span aria-hidden="true">⚠</span>
          {error}
        </div>
      )}

      {report && (
        <>
          <p className="report-panel-note">
            {report.split('\n').length} lines. It includes the limitations, so
            do not delete that section when you submit it.
          </p>
          <pre className="report-preview">{report}</pre>
        </>
      )}
    </div>
  );
}
