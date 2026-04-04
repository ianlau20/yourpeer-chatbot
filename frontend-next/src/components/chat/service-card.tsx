// Copyright (c) 2024 Streetlives, Inc.
//
// Use of this source code is governed by an MIT-style
// license that can be found in the LICENSE file or at
// https://opensource.org/licenses/MIT.

"use client";

import { MapPin, Phone, Mail, Clock } from "lucide-react";
import type { ServiceResult } from "@/lib/chat/types";

interface ServiceCardProps {
  service: ServiceResult;
}

function StatusBadge({ status }: { status?: string }) {
  if (status === "open") {
    return (
      <span className="inline-block text-xs font-semibold px-2.5 py-0.5 rounded-lg bg-green-100 text-green-800">
        Open now
      </span>
    );
  }
  if (status === "closed") {
    return (
      <span className="inline-block text-xs font-semibold px-2.5 py-0.5 rounded-lg bg-red-50 text-red-700">
        Closed
      </span>
    );
  }
  return (
    <span className="inline-block text-xs font-semibold px-2.5 py-0.5 rounded-lg bg-neutral-100 text-neutral-500">
      Call for hours
    </span>
  );
}

export function ServiceCard({ service }: ServiceCardProps) {
  return (
    <div className="flex-shrink-0 w-[280px] snap-start bg-white border border-neutral-200 rounded-2xl p-4 flex flex-col gap-2.5 transition-all hover:border-neutral-300 hover:shadow-md">
      {/* Name */}
      <div className="text-[0.95rem] font-semibold tracking-tight text-neutral-900 leading-snug">
        {service.service_name || "Service"}
      </div>

      {/* Organization */}
      {service.organization && (
        <div className="text-xs text-neutral-500 font-medium -mt-1">
          {service.organization}
        </div>
      )}

      {/* Hours + status */}
      <div className="flex items-center gap-2 flex-wrap">
        <StatusBadge status={service.is_open} />
        {service.hours_today && (
          <span className="inline-flex items-center gap-1 text-xs text-neutral-500">
            <Clock size={14} className="text-neutral-400" />
            {service.hours_today}
          </span>
        )}
      </div>

      {/* Address */}
      {service.address && (
        <div className="flex items-start gap-2 text-sm text-neutral-500 leading-snug">
          <MapPin size={14} className="text-neutral-400 mt-0.5 flex-shrink-0" />
          <span>{service.address}</span>
        </div>
      )}

      {/* Phone */}
      {service.phone && (
        <div className="flex items-start gap-2 text-sm text-neutral-500">
          <Phone size={14} className="text-neutral-400 mt-0.5 flex-shrink-0" />
          <span>{service.phone}</span>
        </div>
      )}

      {/* Email */}
      {service.email && (
        <div className="flex items-start gap-2 text-sm text-neutral-500">
          <Mail size={14} className="text-neutral-400 mt-0.5 flex-shrink-0" />
          <span>{service.email}</span>
        </div>
      )}

      {/* Description */}
      {service.description && (
        <div className="text-xs text-neutral-500 leading-relaxed line-clamp-3">
          {service.description}
        </div>
      )}

      {/* Fee badge */}
      {service.fees && (
        <span className="self-start inline-block text-xs font-semibold text-green-800 bg-green-100 px-2.5 py-0.5 rounded-lg">
          {service.fees}
        </span>
      )}

      {/* Referral badge */}
      {service.requires_membership && (
        <span className="self-start inline-block text-xs font-semibold text-amber-800 bg-amber-100 px-2.5 py-0.5 rounded-lg">
          Referral may be required
        </span>
      )}

      {/* Learn More */}
      {service.yourpeer_url && (
        <a
          href={service.yourpeer_url}
          target="_blank"
          rel="noopener"
          className="block w-full py-2.5 rounded-lg bg-amber-300 text-center text-sm font-semibold text-neutral-900 transition-all hover:bg-amber-400 hover:shadow-md mt-auto"
        >
          Learn More on YourPeer
        </a>
      )}

      {/* Action buttons */}
      <div className="flex gap-1.5 pt-1">
        {service.phone && (
          <a
            href={`tel:${service.phone.replace(/\D/g, "")}`}
            className="flex-1 py-2 rounded-lg border border-neutral-900 bg-neutral-900 text-center text-xs font-semibold text-white transition hover:bg-neutral-700"
          >
            Call
          </a>
        )}
        {service.address && (
          <a
            href={`https://maps.google.com/?q=${encodeURIComponent(service.address)}`}
            target="_blank"
            rel="noopener"
            className="flex-1 py-2 rounded-lg border border-neutral-200 bg-neutral-50 text-center text-xs font-semibold text-neutral-900 transition hover:bg-neutral-100 hover:border-neutral-300"
          >
            Directions
          </a>
        )}
        {service.website && (
          <a
            href={service.website}
            target="_blank"
            rel="noopener"
            className="flex-1 py-2 rounded-lg border border-neutral-200 bg-neutral-50 text-center text-xs font-semibold text-neutral-900 transition hover:bg-neutral-100 hover:border-neutral-300"
          >
            Website
          </a>
        )}
      </div>
    </div>
  );
}
