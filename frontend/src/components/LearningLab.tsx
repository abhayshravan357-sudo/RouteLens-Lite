/**
 * LearningLab
 *
 * Guided exercises for learning routing concepts by doing them.
 *
 * The structure follows one pattern for every concept:
 *   1. What it is
 *   2. Why it matters
 *   3. What happens, step by step
 *   4. A real-life analogy
 *   5. Try it
 *   6. Check the result
 *
 * An exercise is only marked complete when the routing engine's own
 * output satisfies the check. Opening an exercise does nothing.
 */

import { useEffect, useState } from 'react';
import {
  fetchExercise,
  fetchExercises,
  checkExercise,
  updateScenarioRoutes,
} from '../api/routing';
import type {
  ExerciseDetail,
  ExerciseState,
  ExerciseSummary,
} from '../types/routing';
import ProvenanceBadge from './ProvenanceBadge';
import './LearningLab.css';

interface LearningLabProps {
  /** Workspace from a route edit, so exercises check the edited routes. */
  workspace?: string | null;
}

export default function LearningLab({ workspace }: LearningLabProps) {
  const [exercises, setExercises] = useState<ExerciseSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [exercise, setExercise] = useState<ExerciseDetail | null>(null);
  const [state, setState] = useState<ExerciseState | null>(null);
  const [loading, setLoading] = useState(false);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [applied, setApplied] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchExercises()
      .then((list) => {
        if (cancelled) return;
        setExercises(list);
        if (list.length > 0) setSelectedId(list[0].id);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Could not load exercises');
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!selectedId) return;
    let cancelled = false;
    setState(null);
    setApplied(false);
    setError(null);
    fetchExercise(selectedId)
      .then((detail) => {
        if (!cancelled) setExercise(detail);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Could not load the exercise');
        }
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  const runCheck = async () => {
    if (!exercise) return;
    setChecking(true);
    setError(null);
    try {
      const result = await checkExercise(
        exercise.id,
        exercise.scenario_id,
        workspace
      );
      setState(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not check the exercise');
    } finally {
      setChecking(false);
    }
  };

  const applySuggestedRoutes = async () => {
    if (!exercise?.editable_routes || !exercise.editable_node) return;
    setLoading(true);
    setError(null);
    try {
      await updateScenarioRoutes(
        exercise.scenario_id,
        exercise.editable_node,
        exercise.editable_routes
      );
      setApplied(true);
      // Re-check with the edit in place.
      const result = await checkExercise(
        exercise.id,
        exercise.scenario_id,
        workspace
      );
      setState(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not apply the route');
    } finally {
      setLoading(false);
    }
  };

  const completedCount = exercises.filter((e) => {
    return state?.exercise_id === e.id && state.complete;
  }).length;

  return (
    <div className="learning-lab">
      <div className="learning-lab-header">
        <div>
          <h2>Learning Lab</h2>
          <p className="learning-lab-intro">
            Work through these exercises to see routing rules in action. Each one
            is checked against the real routing engine, so an exercise only
            completes when the engine agrees.
          </p>
          {completedCount > 0 && (
            <p className="learning-lab-progress">
              {completedCount} of {exercises.length} exercise
              {exercises.length === 1 ? '' : 's'} completed so far.
            </p>
          )}
        </div>
        <ProvenanceBadge
          provenance="simulated"
          label="Simulated network"
          showDescription
        />
      </div>

      <div className="exercise-layout">
        <nav className="exercise-list" aria-label="Exercises">
          <ul>
            {exercises.map((ex) => {
              const isDone = state?.exercise_id === ex.id && state.complete;
              const isActive = selectedId === ex.id;
              return (
                <li key={ex.id}>
                  <button
                    type="button"
                    className={`exercise-list-item ${isActive ? 'active' : ''} ${
                      isDone ? 'done' : ''
                    }`}
                    onClick={() => setSelectedId(ex.id)}
                    aria-current={isActive}
                  >
                    <span className="exercise-status" aria-hidden="true">
                      {isDone ? '✓' : isActive ? '▸' : '○'}
                    </span>
                    <span className="exercise-list-text">
                      <span className="exercise-list-title">{ex.title}</span>
                      <span className="exercise-list-concept">{ex.concept}</span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </nav>

        <div className="exercise-detail">
          {error && (
            <div className="error-message" role="alert">
              <span aria-hidden="true">⚠</span>
              {error}
            </div>
          )}

          {!exercise ? (
            <div className="loading">
              <span className="spinner" aria-hidden="true" />
              Loading exercise…
            </div>
          ) : (
            <>
              <h3 className="exercise-title">{exercise.title}</h3>

              <section className="exercise-section">
                <h4>1. What it is</h4>
                <p>{exercise.what_it_is}</p>
              </section>

              <section className="exercise-section">
                <h4>2. Why it matters</h4>
                <p>{exercise.why_it_matters}</p>
              </section>

              <section className="exercise-section">
                <h4>3. What happens</h4>
                <p>{exercise.what_happens}</p>
              </section>

              <section className="exercise-section exercise-analogy">
                <h4>4. In real life</h4>
                <p>{exercise.analogy}</p>
              </section>

              <section className="exercise-section">
                <h4>5. Try it</h4>
                <p>{exercise.instruction}</p>
                <p className="exercise-parameters">
                  From <code>{exercise.source}</code> to{' '}
                  <code>{exercise.destination}</code> in scenario{' '}
                  <code>{exercise.scenario_id}</code>
                </p>
                {exercise.editable_routes && exercise.editable_routes.length > 0 && (
                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={applySuggestedRoutes}
                    disabled={loading}
                  >
                    {loading
                      ? 'Applying…'
                      : `Apply the suggested route to ${exercise.editable_node}`}
                  </button>
                )}
                {applied && (
                  <p className="exercise-applied">
                    The route was applied. Check the result again.
                  </p>
                )}
              </section>

              <section className="exercise-section">
                <h4>Before you check</h4>
                <p className="exercise-prediction">{exercise.prediction_prompt}</p>
              </section>

              <section className="exercise-section">
                <h4>6. Check the result</h4>
                <p className="exercise-hint">{exercise.result_hint}</p>
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={runCheck}
                  disabled={checking}
                >
                  {checking ? 'Checking…' : 'Check my answer'}
                </button>

                {state && (
                  <div
                    className={`exercise-result ${state.complete ? 'complete' : 'incomplete'}`}
                  >
                    <div className="exercise-result-header">
                      <span className="exercise-verdict">
                        {state.complete ? 'Correct' : 'Not yet'}
                      </span>
                      {state.trace_status && (
                        <span className="exercise-trace-status">
                          trace ended: {state.trace_status}
                        </span>
                      )}
                      {state.selected_route && (
                        <span className="exercise-trace-status">
                          route used: <code>{state.selected_route}</code>
                          {state.selected_prefix_length !== null &&
                            ` (/${state.selected_prefix_length})`}
                        </span>
                      )}
                    </div>

                    <ul className="exercise-checks">
                      {state.checks.map((check, i) => (
                        <li
                          key={i}
                          className={check.satisfied ? 'satisfied' : 'unsatisfied'}
                        >
                          <span className="check-icon" aria-hidden="true">
                            {check.satisfied ? '✓' : '✗'}
                          </span>
                          <span className="check-description">
                            {check.description}
                          </span>
                          {check.detail && (
                            <span className="check-detail">{check.detail}</span>
                          )}
                        </li>
                      ))}
                    </ul>

                    {state.complete && state.explanation && (
                      <div className="exercise-takeaway">
                        <h5>What this shows</h5>
                        <p>{state.explanation}</p>
                      </div>
                    )}

                    {state.hops.length > 0 && (
                      <details className="exercise-hops">
                        <summary>The hops the engine traced</summary>
                        <ol>
                          {state.hops.map((hop) => (
                            <li key={hop.hop_number}>
                              <span className="mono">{hop.node}</span>{' '}
                              <em>{hop.action}</em>
                              {hop.matched_prefix && (
                                <span className="mono"> {hop.matched_prefix}</span>
                              )}
                              <p>{hop.explanation}</p>
                            </li>
                          ))}
                        </ol>
                      </details>
                    )}
                  </div>
                )}
              </section>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
