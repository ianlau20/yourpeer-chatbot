// Copyright (c) 2024 Streetlives, Inc.
//
// Use of this source code is governed by an MIT-style
// license that can be found in the LICENSE file or at
// https://opensource.org/licenses/MIT.

"use client";

import { useRef, useState, useCallback } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { ServiceCard } from "./service-card";
import type { ServiceResult } from "@/lib/chat/types";

interface ServiceCarouselProps {
  services: ServiceResult[];
}

export function ServiceCarousel({ services }: ServiceCarouselProps) {
  const trackRef = useRef<HTMLDivElement>(null);
  const [currentIndex, setCurrentIndex] = useState(0);

  const scrollToIndex = useCallback(
    (index: number) => {
      if (!trackRef.current || !trackRef.current.firstElementChild) return;
      const cardWidth = (trackRef.current.firstElementChild as HTMLElement).offsetWidth;
      trackRef.current.scrollLeft = index * (cardWidth + 12);
    },
    [],
  );

  function handleScroll() {
    if (!trackRef.current || !trackRef.current.firstElementChild) return;
    const cardWidth = (trackRef.current.firstElementChild as HTMLElement).offsetWidth;
    const idx = Math.round(trackRef.current.scrollLeft / (cardWidth + 12));
    const clamped = Math.min(idx, services.length - 1);
    if (clamped !== currentIndex) setCurrentIndex(clamped);
  }

  return (
    <div className="self-start w-full animate-in fade-in slide-in-from-bottom-1">
      {/* Header */}
      <div className="flex items-center justify-between px-1 pb-2">
        <span className="text-xs text-neutral-400 font-medium">
          {currentIndex + 1} of {services.length}
        </span>
        <div className="flex gap-1">
          <button
            type="button"
            disabled={currentIndex === 0}
            onClick={() => scrollToIndex(currentIndex - 1)}
            className="w-8 h-8 rounded-full border border-neutral-200 bg-white text-neutral-500 flex items-center justify-center transition hover:bg-neutral-50 hover:border-neutral-300 disabled:opacity-30 disabled:cursor-default"
          >
            <ChevronLeft size={16} />
          </button>
          <button
            type="button"
            disabled={currentIndex >= services.length - 1}
            onClick={() => scrollToIndex(currentIndex + 1)}
            className="w-8 h-8 rounded-full border border-neutral-200 bg-white text-neutral-500 flex items-center justify-center transition hover:bg-neutral-50 hover:border-neutral-300 disabled:opacity-30 disabled:cursor-default"
          >
            <ChevronRight size={16} />
          </button>
        </div>
      </div>

      {/* Track */}
      <div
        ref={trackRef}
        onScroll={handleScroll}
        className="flex gap-3 overflow-x-auto snap-x snap-mandatory scroll-smooth pb-2 scrollbar-hide"
      >
        {services.map((svc, i) => (
          <ServiceCard key={i} service={svc} />
        ))}
      </div>

      {/* Dots */}
      {services.length > 1 && (
        <div className="flex justify-center gap-1.5 pt-1">
          {services.map((_, i) => (
            <div
              key={i}
              className={`h-1.5 rounded-full transition-all ${
                i === currentIndex
                  ? "w-4 bg-neutral-900"
                  : "w-1.5 bg-neutral-300"
              }`}
            />
          ))}
        </div>
      )}
    </div>
  );
}
