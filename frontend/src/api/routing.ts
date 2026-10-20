/**
 * API module for communicating with the RouteLens Lite backend.
 * All requests are proxied through Vite to http://localhost:8000.
 */

import type { RoutingEntry, RouteLookupResult } from '../types/routing';

const API_BASE = '';
const DEFAULT_TIMEOUT = 10000;

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code?: string
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export class TimeoutError extends Error {
  constructor(message = 'Request timed out') {
    super(message);
    this.name = 'TimeoutError';
  }
}

export class LabUnavailableError extends Error {
  constructor(message = 'Packet lab is currently unavailable') {
    super(message);
    this.name = 'LabUnavailableError';
  }
}

async function fetchWithTimeout<T>(
  endpoint: string,
  timeoutMs = DEFAULT_TIMEOUT
): Promise<T> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`${API_BASE}${endpoint}`, {
      signal: controller.signal,
    });

    clearTimeout(timeoutId);

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Unknown error' }));

      if (response.status === 503 && error.detail?.includes('lab')) {
        throw new LabUnavailableError(error.detail);
      }

      throw new ApiError(
        error.detail || `Request failed: ${response.status}`,
        response.status,
        error.code
      );
    }

    return response.json();
  } catch (error) {
    clearTimeout(timeoutId);

    if (error instanceof ApiError || error instanceof LabUnavailableError) {
      throw error;
    }

    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new TimeoutError();
    }

    throw new ApiError(
      error instanceof Error ? error.message : 'Network error',
      0,
      'NETWORK_ERROR'
    );
  }
}

export async function checkHealth(): Promise<{ status: string; service: string }> {
  return fetchWithTimeout<{ status: string; service: string }>('/health', 5000);
}

export async function fetchRoutes(): Promise<RoutingEntry[]> {
  return fetchWithTimeout<RoutingEntry[]>('/routes');
}

export async function lookupRoute(destination: string): Promise<RouteLookupResult> {
  const encoded = encodeURIComponent(destination);
  return fetchWithTimeout<RouteLookupResult>(`/lookup?destination=${encoded}`);
}