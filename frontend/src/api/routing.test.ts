import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fetchReportJson, fetchReportMarkdown } from '../api/routing';

describe('fetchReportJson', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('calls fetch with the report JSON endpoint', async () => {
    const mockFetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: 'ok' }), { status: 200 }));
    vi.spyOn(window, 'fetch').mockImplementation(mockFetch);

    await fetchReportJson();

    expect(mockFetch).toHaveBeenCalledWith(
      '/api/report?format=json',
      expect.objectContaining({ signal: expect.any(AbortSignal) })
    );
  });

  it('returns the JSON response', async () => {
    const mockFetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ report: 'data' }), { status: 200 }));
    vi.spyOn(window, 'fetch').mockImplementation(mockFetch);

    const result = await fetchReportJson();

    expect(result).toEqual({ report: 'data' });
  });
});

describe('fetchReportMarkdown', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('calls fetch with GET markdown endpoint when no experiment', async () => {
    const mockFetch = vi.fn().mockResolvedValue(new Response('# Report', { status: 200 }));
    vi.spyOn(window, 'fetch').mockImplementation(mockFetch);

    await fetchReportMarkdown();

    expect(mockFetch).toHaveBeenCalledWith(
      '/api/report?format=markdown',
      expect.objectContaining({ signal: expect.any(AbortSignal) })
    );
  });

  it('returns markdown text for GET', async () => {
    const mockFetch = vi.fn().mockResolvedValue(new Response('# Report Title', { status: 200 }));
    vi.spyOn(window, 'fetch').mockImplementation(mockFetch);

    const result = await fetchReportMarkdown();

    expect(result).toBe('# Report Title');
  });

  it('calls fetch POST when activeExperiment is provided', async () => {
    const mockFetch = vi.fn().mockResolvedValue(new Response('# Experiment Report', { status: 200 }));
    vi.spyOn(window, 'fetch').mockImplementation(mockFetch);

    const experiment = { scenarioId: 's1', before: {}, after: {} };

    await fetchReportMarkdown(experiment);

    expect(mockFetch).toHaveBeenCalledWith(
      '/api/report',
      expect.objectContaining({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          format: 'markdown',
          active_experiment: experiment,
        }),
        signal: expect.any(AbortSignal),
      })
    );
  });

  it('returns markdown text for POST', async () => {
    const mockFetch = vi.fn().mockResolvedValue(new Response('# Experiment Report', { status: 200 }));
    vi.spyOn(window, 'fetch').mockImplementation(mockFetch);

    const result = await fetchReportMarkdown({ scenarioId: 's1' });

    expect(result).toBe('# Experiment Report');
  });

  it('throws on non-2xx response', async () => {
    const mockFetch = vi.fn().mockResolvedValue(new Response('Error', { status: 500, statusText: 'Internal Server Error' }));
    vi.spyOn(window, 'fetch').mockImplementation(mockFetch);

    await expect(fetchReportMarkdown()).rejects.toThrow();
  });
});
