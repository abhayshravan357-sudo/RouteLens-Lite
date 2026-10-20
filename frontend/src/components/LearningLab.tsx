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
 *
 * There are two sets of exercises, kept apart because they are about
 * different things. The modelled ones run against a network the student
 * is given. The host ones run against the routing table of the machine
 * they are sitting at, which is the thing they will actually meet.
 */

import { useEffect, useState } from 'react';
import {
  fetchExercise,
  fetchExercises,
  checkExercise,
  updateScenarioRoutes,
  fetchHostExercises,
  fetchHostExercise,
  checkHostExercise,
} from '../api/routing';
import type {
  ExerciseDetail,
  ExerciseState,
  ExerciseSummary,
  HostExerciseDetail,
  HostExerciseState,
  HostExerciseSummary,
} from '../types/routing';
import ProvenanceBadge from './ProvenanceBadge';
import './LearningLab.css';

interface LearningLabProps {
  /** Workspace from a route edit, so exercises check the edited routes. */
  workspace?: string | null;
}

export default function LearningLab({ workspace }: LearningLabProps) {
  const [exercises, setExercises] = useState<ExerciseSummary[]>([]);
  const [hostExercises, setHostExercises] = useState<HostExerciseSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [exercise, setExercise] = useState<ExerciseDetail | null>(null);
  const [hostExercise, setHostExercise] = useState<HostExerciseDetail | null>(null);
  const [state, setState] = useState<ExerciseState | null>(null);
  const [hostState, setHostState] = useState<HostExerciseState | null>(null);
  const [loading, setLoading] = useState(false);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [applied, setApplied] = useState(false);
  /** The address the student picked for a host exercise. */
  const [hostDestination, setHostDestination] = useState('');
  /** What the student thinks the answer is. */
  const [hostAnswer, setHostAnswer] = useState('');

  /** A host exercise is one that works against this machine's own table. */
  const isHostExercise = selectedId?.startsWith('host-') ?? false;

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
    // The host exercises are a separate set and a separate endpoint. If
    // they are not there, the modelled ones still work.
    fetchHostExercises()
      .then((list) => {
        if (!cancelled) setHostExercises(list);
      })
      .catch(() => {
        if (!cancelled) setHostExercises([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!selectedId) return;
    let cancelled = false;
    setState(null);
    setHostState(null);
    setApplied(false);
    setError(null);

    if (selectedId.startsWith('host-')) {
      setExercise(null);
      fetchHostExercise(selectedId)
        .then((detail) => {
          if (!cancelled) setHostExercise(detail);
        })
        .catch((err) => {
          if (!cancelled) {
            setError(err instanceof Error ? err.message : 'Could not load the exercise');
          }
        });
      return () => {
        cancelled = true;
      };
    }

    setHostExercise(null);
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
    if (isHostExercise) {
      if (!hostExercise) return;
      setChecking(true);
      setError(null);
      try {
        const result = await checkHostExercise(
          hostExercise.id,
          hostDestination,
          hostAnswer
        );
        setHostState(result);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Could not check the exercise');
      } finally {
        setChecking(false);
      }
      return;
    }

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

  const completedCount =
    exercises.filter((e) => state?.exercise_id === e.id && state.complete).length +
    hostExercises.filter((e) => hostState?.exercise_id === e.id && hostState.complete)
      .length;

  const totalCount = exercises.length + hostExercises.length;

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
              {completedCount} of {totalCount} exercise
              {totalCount === 1 ? '' : 's'} completed so far.
            </p>
          )}
        </div>
        <ProvenanceBadge
          provenance={isHostExercise ? 'observed' : 'simulated'}
          label={isHostExercise ? 'Your machine' : 'Simulated network'}
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

          {hostExercises.length > 0 && (
            <>
              <p className="exercise-list-group">On your own machine</p>
              <ul>
                {hostExercises.map((ex) => {
                  const isDone = hostState?.exercise_id === ex.id && hostState.complete;
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
            </>
          )}
        </nav>

        <div className="exercise-detail">
          {error && (
            <div className="error-message" role="alert">
              <span aria-hidden="true">⚠</span>
              {error}
            </div>
          )}

          {hostExercise ? (
            <>
              <h3 className="exercise-title">{hostExercise.title}</h3>

              <section className="exercise-section">
                <h4>1. What it is</h4>
                <p>{hostExercise.what_it_is}</p>
              </section>

              <section className="exercise-section">
                <h4>2. Why it matters</h4>
                <p>{hostExercise.why_it_matters}</p>
              </section>

              <section className="exercise-section">
                <h4>3. What happens</h4>
                <p>{hostExercise.what_happens}</p>
              </section>

              <section className="exercise-section exercise-analogy">
                <h4>4. In real life</h4>
                <p>{hostExercise.analogy}</p>
              </section>

              <section className="exercise-section">
                <h4>5. Try it</h4>
                <p>{hostExercise.instruction}</p>
                <div className="host-exercise-form">
                  <div className="input-group">
                    <label htmlFor="host-destination">Address to look up</label>
                    <input
                      id="host-destination"
                      type="text"
                      value={hostDestination}
                      onChange={(e) => setHostDestination(e.target.value)}
                      placeholder="Leave empty to use one of your machine's own addresses"
                      spellCheck={false}
                      disabled={checking}
                    />
                  </div>
                  <div className="input-group">
                    <label htmlFor="host-answer">Your answer</label>
                    <input
                      id="host-answer"
                      type="text"
                      value={hostAnswer}
                      onChange={(e) => setHostAnswer(e.target.value)}
                      placeholder="What do you think your machine would use?"
                      spellCheck={false}
                      disabled={checking}
                    />
                  </div>
                </div>
              </section>

              <section className="exercise-section">
                <h4>Before you check</h4>
                <p className="exercise-prediction">{hostExercise.prediction_prompt}</p>
              </section>

              <section className="exercise-section">
                <h4>6. Check the result</h4>
                <p className="exercise-hint">{hostExercise.result_hint}</p>
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={runCheck}
                  disabled={checking}
                >
                  {checking ? 'Checking…' : 'Check my answer'}
                </button>

                {hostState && (
                  <div
                    className={`exercise-result ${
                      hostState.complete ? 'complete' : 'incomplete'
                    }`}
                  >
                    <div className="exercise-result-header">
                      <span className="exercise-verdict">
                        {hostState.complete ? 'Correct' : 'Not yet'}
                      </span>
                      {hostState.table_provenance === 'observed' &&
                        hostState.analysis_provenance === 'inferred' && (
                          <span className="exercise-trace-status">
                            table observed, conclusion inferred
                          </span>
                        )}
                      {hostState.selected_route && (
                        <span className="exercise-trace-status">
                          route used: <code>{hostState.selected_route}</code>
                          {hostState.selected_prefix_length !== null &&
                            ` (/${hostState.selected_prefix_length})`}
                        </span>
                      )}
                    </div>

                    {!hostState.available && (
                      <div className="exercise-unavailable">
                        <p>{hostState.unavailable_reason ?? hostState.message}</p>
                        {hostExercise.unavailable_hint && (
                          <p className="exercise-unavailable-hint">
                            {hostExercise.unavailable_hint}
                          </p>
                        )}
                      </div>
                    )}

                    {hostState.message && hostState.available && (
                      <p className="exercise-message">{hostState.message}</p>
                    )}

                    {hostState.checks.length > 0 && (
                      <ul className="exercise-checks">
                        {hostState.checks.map((check, i) => (
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
                    )}

                    {hostState.complete && hostState.explanation && (
                      <div className="exercise-takeaway">
                        <h5>What this shows</h5>
                        <p>{hostState.explanation}</p>
                      </div>
                    )}

                    {hostState.limitations.length > 0 && (
                      <details className="exercise-hops">
                        <summary>What this check could not establish</summary>
                        <ul>
                          {hostState.limitations.map((limitation, i) => (
                            <li key={i}>{limitation}</li>
                          ))}
                        </ul>
                      </details>
                    )}
                  </div>
                )}
              </section>
            </>
          ) : exercise ? (
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
          ) : (
            <div className="loading">
              <span className="spinner" aria-hidden="true" />
              Loading exercise…
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
