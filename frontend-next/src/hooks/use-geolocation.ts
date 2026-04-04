// Copyright (c) 2024 Streetlives, Inc.
//
// Use of this source code is governed by an MIT-style
// license that can be found in the LICENSE file or at
// https://opensource.org/licenses/MIT.

"use client";

import { useState, useCallback } from "react";

interface GeolocationState {
  latitude: number | null;
  longitude: number | null;
  error: string | null;
  loading: boolean;
}

export function useGeolocation() {
  const [state, setState] = useState<GeolocationState>({
    latitude: null,
    longitude: null,
    error: null,
    loading: false,
  });

  const requestLocation = useCallback((): Promise<{ latitude: number; longitude: number } | null> => {
    if (!navigator.geolocation) {
      setState((s) => ({ ...s, error: "Geolocation is not supported by your browser." }));
      return Promise.resolve(null);
    }

    setState((s) => ({ ...s, loading: true, error: null }));

    return new Promise((resolve) => {
      navigator.geolocation.getCurrentPosition(
        (position) => {
          const coords = {
            latitude: position.coords.latitude,
            longitude: position.coords.longitude,
          };
          setState({
            ...coords,
            error: null,
            loading: false,
          });
          resolve(coords);
        },
        (err) => {
          let message: string;
          switch (err.code) {
            case err.PERMISSION_DENIED:
              message = "Location access was denied. You can pick a borough instead.";
              break;
            case err.POSITION_UNAVAILABLE:
              message = "Couldn't determine your location. You can pick a borough instead.";
              break;
            case err.TIMEOUT:
              message = "Location request timed out. You can pick a borough instead.";
              break;
            default:
              message = "Couldn't get your location. You can pick a borough instead.";
          }
          setState({ latitude: null, longitude: null, error: message, loading: false });
          resolve(null);
        },
        { enableHighAccuracy: false, timeout: 10_000, maximumAge: 300_000 },
      );
    });
  }, []);

  return {
    ...state,
    hasCoords: state.latitude !== null && state.longitude !== null,
    requestLocation,
  };
}
