/**
 * RouteEditor
 *
 * Lets a route be changed on a node, then traced again to see the
 * difference.
 *
 * The editor works on a copy. Saving sends the new routes to the
 * backend, which validates them and returns the updated scenario. The
 * shared scenario is never edited in place, so a bad edit cannot break
 * anyone else's trace.
 */

import { useEffect, useRef, useState } from 'react';
import { updateScenarioRoutes } from '../api/routing';
import type { Scenario, ScenarioRoute } from '../types/routing';
import './RouteEditor.css';

interface RouteEditorProps {
  scenario: Scenario | null;
  nodeId: string;
  onSaved: (scenario: Scenario, workspace: string) => void;
}

interface DraftRoute {
  prefix: string;
  dev: string;
  via: string;
  metric: string;
}

const EMPTY_DRAFT: DraftRoute = { prefix: '', dev: '', via: '', metric: '10' };

function toDraft(route: ScenarioRoute): DraftRoute {
  return {
    prefix: route.prefix,
    dev: route.dev,
    via: route.via ?? '',
    metric: String(route.metric),
  };
}

export default function RouteEditor({ scenario, nodeId, onSaved }: RouteEditorProps) {
  const [drafts, setDrafts] = useState<DraftRoute[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  // Set while our own save is in flight, so the effect that reloads the
  // drafts does not wipe the confirmation the user just earned.
  const savingJustNow = useRef(false);

  // Load the node's current routes whenever the scenario or node changes.
  useEffect(() => {
    if (!scenario) {
      setDrafts([]);
      return;
    }
    const node = scenario.nodes.find((n) => n.id === nodeId);
    setDrafts(node ? node.routes.map(toDraft) : []);
    setError(null);
    if (savingJustNow.current) {
      // This is the scenario we just saved ourselves. Keep the confirmation.
      savingJustNow.current = false;
    } else {
      setSaved(false);
    }
  }, [scenario, nodeId]);

  if (!scenario) return null;

  const node = scenario.nodes.find((n) => n.id === nodeId);
  if (!node) return null;

  const updateDraft = (index: number, field: keyof DraftRoute, value: string) => {
    setDrafts((prev) =>
      prev.map((d, i) => (i === index ? { ...d, [field]: value } : d))
    );
    setSaved(false);
  };

  const addRow = () => {
    setDrafts((prev) => [...prev, { ...EMPTY_DRAFT }]);
    setSaved(false);
  };

  const removeRow = (index: number) => {
    setDrafts((prev) => prev.filter((_, i) => i !== index));
    setSaved(false);
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    savingJustNow.current = true;
    try {
      const routes = drafts.map((d) => ({
        prefix: d.prefix.trim(),
        dev: d.dev.trim(),
        via: d.via.trim() ? d.via.trim() : null,
        metric: parseInt(d.metric, 10) || 0,
      }));
      const updated = await updateScenarioRoutes(scenario.id, nodeId, routes);
      onSaved(updated.scenario, updated.workspace);
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save the routes');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="route-editor">
      <div className="route-editor-header">
        <div>
          <h4>Edit routes on {node.id}</h4>
          <p className="route-editor-note">
            Change a route, save it, then trace a packet again to see whether the
            forwarding decision changed.
          </p>
        </div>
        <div className="route-editor-actions">
          <button type="button" className="btn btn-sm btn-secondary" onClick={addRow}>
            + Add route
          </button>
          <button
            type="button"
            className="btn btn-sm btn-primary"
            onClick={handleSave}
            disabled={saving}
          >
            {saving ? 'Saving…' : 'Save routes'}
          </button>
        </div>
      </div>

      {error && (
        <div className="error-message" role="alert">
          <span aria-hidden="true">⚠</span>
          {error}
        </div>
      )}
      {saved && !error && (
        <div className="route-editor-saved">
          Saved. Trace a packet again to see the difference.
        </div>
      )}

      <table className="route-editor-table">
        <thead>
          <tr>
            <th scope="col">Destination</th>
            <th scope="col">Next hop</th>
            <th scope="col">Interface</th>
            <th scope="col">Metric</th>
            <th scope="col" aria-label="Actions" />
          </tr>
        </thead>
        <tbody>
          {drafts.length === 0 && (
            <tr>
              <td colSpan={5} className="route-editor-empty">
                {node.kind === 'host'
                  ? 'This host has no static routes. Its connected networks are added automatically.'
                  : 'No static routes. Add one, or leave it to route only its connected networks.'}
              </td>
            </tr>
          )}
          {drafts.map((draft, index) => (
            <tr key={index}>
              <td>
                <input
                  type="text"
                  value={draft.prefix}
                  onChange={(e) => updateDraft(index, 'prefix', e.target.value)}
                  placeholder="0.0.0.0/0"
                  spellCheck={false}
                  aria-label={`Destination for route ${index + 1}`}
                />
              </td>
              <td>
                <input
                  type="text"
                  value={draft.via}
                  onChange={(e) => updateDraft(index, 'via', e.target.value)}
                  placeholder="direct"
                  spellCheck={false}
                  aria-label={`Next hop for route ${index + 1}`}
                />
              </td>
              <td>
                <input
                  type="text"
                  value={draft.dev}
                  onChange={(e) => updateDraft(index, 'dev', e.target.value)}
                  placeholder="eth0"
                  spellCheck={false}
                  aria-label={`Interface for route ${index + 1}`}
                />
              </td>
              <td>
                <input
                  type="number"
                  value={draft.metric}
                  onChange={(e) => updateDraft(index, 'metric', e.target.value)}
                  min="0"
                  aria-label={`Metric for route ${index + 1}`}
                />
              </td>
              <td>
                <button
                  type="button"
                  className="route-editor-remove"
                  onClick={() => removeRow(index)}
                  aria-label={`Remove route ${index + 1}`}
                >
                  ✕
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
