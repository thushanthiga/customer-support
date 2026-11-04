"use client";

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod/v3";

const schema = z.object({
  email: z.string().email().max(255),
  password: z.string().min(1, "Enter your ERP password").max(512),
  tenant: z.string().trim().min(1).max(255),
});
type Credentials = z.infer<typeof schema>;
export type ErpUser = { name: string; user_id: number; tenant: string; analytics_access?: "admin" | "erp" };

export default function ErpSignIn({ onSignIn, model }: { onSignIn: (user: ErpUser) => void; model?: string }) {
  const { register, handleSubmit, setError, formState: { errors, isSubmitting } } = useForm<Credentials>({
    resolver: zodResolver(schema), defaultValues: { tenant: "" },
  });
  const submit = async (data: Credentials) => {
    try {
      const result = await fetch("/api/auth/erp/login/", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data),
      });
      const body = await result.json();
      if (!result.ok) { setError("root", { message: body.error || "Sign-in failed" }); return; }
      onSignIn(body.user);
    } catch { setError("root", { message: "The ERP sign-in service is unavailable." }); }
  };
  return <main className="min-h-screen grid place-items-center bg-slate-950 text-slate-100 p-6">
    <form onSubmit={handleSubmit(submit)} className="w-full max-w-sm space-y-5 rounded-2xl border border-slate-700 bg-slate-900 p-7">
      <div><h1 className="text-xl font-semibold">Sign in to Apptimate Copilot</h1>
        <p className="mt-2 text-sm text-slate-400">Use your ERP account to query your connected tenant’s business data.</p></div>
      <label className="block text-sm">Tenant<input {...register("tenant")} placeholder="Tenant ID or registered domain" autoComplete="organization" className="mt-1 w-full rounded-lg bg-slate-800 p-3" /></label>
      <label className="block text-sm">ERP email<input {...register("email")} type="email" autoComplete="username" className="mt-1 w-full rounded-lg bg-slate-800 p-3" /></label>
      <label className="block text-sm">Password<input {...register("password")} type="password" autoComplete="current-password" className="mt-1 w-full rounded-lg bg-slate-800 p-3" /></label>
      {Object.entries(errors).map(([key, error]) => <p key={key} role="alert" className="text-sm text-rose-300">{error.message}</p>)}
      <button disabled={isSubmitting} className="w-full rounded-lg bg-indigo-600 p-3 font-medium disabled:opacity-50">{isSubmitting ? "Signing in…" : "Sign in"}</button>
      <p className="text-xs text-slate-400">{`Business records come from the configured database. Query planning uses ${model || "the configured chat model"}.`}</p>
    </form>
  </main>;
}
