// Copyright (c) 2024 Streetlives, Inc.
//
// Use of this source code is governed by an MIT-style
// license that can be found in the LICENSE file or at
// https://opensource.org/licenses/MIT.

"use client";

export function LogoutButton() {
  async function handleLogout() {
    await fetch("/api/admin/auth", { method: "DELETE" });
    window.location.reload();
  }

  return (
    <button
      onClick={handleLogout}
      className="text-sm text-neutral-400 hover:text-neutral-600 transition-colors"
    >
      Sign out
    </button>
  );
}
