// Copyright (c) 2024 Streetlives, Inc.
//
// Use of this source code is governed by an MIT-style
// license that can be found in the LICENSE file or at
// https://opensource.org/licenses/MIT.

import type { Metadata } from "next";
import { AdminNav } from "@/components/admin/admin-nav";
import { AdminAuthGuard } from "@/components/admin/admin-auth-guard";
import { LogoutButton } from "@/components/admin/logout-button";

export const metadata: Metadata = {
  title: "YourPeer — Staff Review Console",
};

export default function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <AdminAuthGuard>
      <div className="min-h-dvh bg-neutral-100">
        <div className="max-w-[1280px] mx-auto px-7 py-6">
          <header className="flex items-center justify-between pb-5 border-b border-neutral-300 mb-6">
            <div className="flex items-baseline gap-3">
              <h1 className="text-xl font-bold tracking-tight text-amber-500">
                YourPeer
              </h1>
              <span className="text-sm text-neutral-400">
                Staff Review Console
              </span>
            </div>
            <LogoutButton />
          </header>

          <AdminNav />

          {children}
        </div>
      </div>
    </AdminAuthGuard>
  );
}
