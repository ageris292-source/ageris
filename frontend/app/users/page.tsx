"use client";

import { Check, Copy, KeyRound, Lock, MoreHorizontal, UserPlus, Users } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { usePageTitle } from "@/components/usePageTitle";
import { useSession } from "@/components/providers/SessionProvider";
import { useToast } from "@/components/providers/ToastProvider";
import { ConfirmDialog, Dialog } from "@/components/ui/Dialog";
import {
  Badge,
  Button,
  Callout,
  Card,
  EmptyState,
  Field,
  Input,
  LoadingRows,
  PageHeader,
  Select,
  Table,
  Td,
  Th,
  cx,
} from "@/components/ui/core";
import { api, ApiError, type InviteResult, type UserAdmin } from "@/lib/api";
import { ago, istDate } from "@/lib/format";

function CopyField({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex items-center gap-2 rounded-lg border border-line bg-sunken p-2 pl-3">
      <code className="flex-1 select-all break-all font-mono text-base tracking-wide">{value}</code>
      <Button
        size="sm"
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(value);
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
          } catch {
            /* clipboard blocked: the value is selectable */
          }
        }}
        icon={copied ? <Check size={14} /> : <Copy size={14} />}
      >
        {copied ? "Copied" : "Copy"}
      </Button>
    </div>
  );
}

function RowMenu({ u, self, onAction }: { u: UserAdmin; self: boolean; onAction: (a: "reset" | "toggle") => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);
  if (self) return <span className="text-xs text-subtle">You</span>;
  return (
    <div ref={ref} className="relative inline-block">
      <button onClick={() => setOpen((v) => !v)} aria-haspopup="menu" aria-expanded={open} aria-label={`Actions for ${u.email}`} className="rounded-md p-1.5 text-muted hover:bg-hover hover:text-ink">
        <MoreHorizontal size={16} />
      </button>
      {open && (
        <div role="menu" className="animate-in absolute right-0 z-20 mt-1 w-52 rounded-lg border border-line bg-elevated p-1 text-left shadow-[var(--shadow-pop)]">
          <button role="menuitem" onClick={() => { setOpen(false); onAction("reset"); }} className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm hover:bg-hover">
            <KeyRound size={14} aria-hidden /> Reset password
          </button>
          <button role="menuitem" onClick={() => { setOpen(false); onAction("toggle"); }} className={cx("flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm hover:bg-hover", u.is_active && "text-fail")}>
            <Lock size={14} aria-hidden /> {u.is_active ? "Deactivate" : "Reactivate"}
          </button>
        </div>
      )}
    </div>
  );
}

export default function UsersPage() {
  usePageTitle("Users");
  const { guard, isAdmin, me } = useSession();
  const toast = useToast();
  const [users, setUsers] = useState<UserAdmin[] | null>(null);
  const [inviteOpen, setInviteOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<"analyst" | "admin">("analyst");
  const [busy, setBusy] = useState(false);
  const [secret, setSecret] = useState<{ title: string; result: InviteResult } | null>(null);
  const [pending, setPending] = useState<{ u: UserAdmin; action: "reset" | "toggle" } | null>(null);

  const load = useCallback(async () => {
    try {
      const u = await guard((t) => api.users(t));
      if (u) setUsers(u);
    } catch (err) {
      toast({ tone: "error", title: "Could not load users", body: err instanceof Error ? err.message : undefined });
    }
  }, [guard, toast]);

  useEffect(() => {
    if (isAdmin) void load();
  }, [isAdmin, load]);

  async function invite(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const r = await guard((t) => api.inviteUser(t, email.trim(), role));
      if (r) {
        setInviteOpen(false);
        setEmail("");
        setRole("analyst");
        setSecret({ title: `Invited ${r.user.email}`, result: r });
      }
      await load();
    } catch (err) {
      toast({ tone: "error", title: "Invite failed", body: err instanceof ApiError ? err.message : undefined });
    } finally {
      setBusy(false);
    }
  }

  async function changeRole(u: UserAdmin, r: "admin" | "analyst") {
    try {
      await guard((t) => api.updateUser(t, u.id, { role: r }));
      toast({ tone: "success", title: `${u.email} is now ${r === "admin" ? "an admin" : "an analyst"}`, body: "Their existing sessions were signed out." });
      await load();
    } catch (err) {
      toast({ tone: "error", title: "Role not changed", body: err instanceof ApiError ? err.message : undefined });
      await load();
    }
  }

  async function confirmAction() {
    if (!pending) return;
    setBusy(true);
    try {
      if (pending.action === "reset") {
        const r = await guard((t) => api.resetUserPassword(t, pending.u.id));
        if (r) setSecret({ title: `New temporary password for ${r.user.email}`, result: r });
      } else {
        await guard((t) => api.updateUser(t, pending.u.id, { is_active: !pending.u.is_active }));
        toast({ tone: "success", title: pending.u.is_active ? `Deactivated ${pending.u.email}` : `Reactivated ${pending.u.email}` });
      }
      setPending(null);
      await load();
    } catch (err) {
      toast({ tone: "error", title: "Not changed", body: err instanceof ApiError ? err.message : undefined });
    } finally {
      setBusy(false);
    }
  }

  if (!isAdmin) {
    return (
      <Card>
        <EmptyState icon={<Lock size={20} />} title="Admins only" body="Ask an admin to manage team access." />
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Users"
        description="Invite people to Aegis and control what they can do. There is no public sign-up."
        actions={<Button variant="primary" icon={<UserPlus size={15} />} onClick={() => setInviteOpen(true)}>Invite user</Button>}
      />

      <div className="grid items-start gap-6 xl:grid-cols-3">
        <Card className="xl:col-span-2" bodyClassName="pb-2" title="Team" description={users ? `${users.filter((u) => u.is_active).length} active of ${users.length}` : undefined}>
          {users === null && <LoadingRows rows={4} />}
          {users && users.length > 0 && (
            <Table>
              <thead>
                <tr>
                  <Th>User</Th>
                  <Th>Role</Th>
                  <Th className="hidden sm:table-cell">Status</Th>
                  <Th className="hidden md:table-cell">Last sign-in</Th>
                  <Th />
                </tr>
              </thead>
              <tbody>
                {users.map((u) => {
                  const self = u.email === me?.email;
                  return (
                    <tr key={u.id} className={cx(!u.is_active && "opacity-60")}>
                      <Td>
                        <div className="flex items-center gap-3">
                          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-sunken text-xs font-semibold text-muted">{u.email.slice(0, 2).toUpperCase()}</span>
                          <div className="min-w-0">
                            <p className="truncate font-medium">{u.email}</p>
                            <p className="text-xs text-subtle">Joined {istDate(u.created_at)}</p>
                          </div>
                        </div>
                      </Td>
                      <Td>
                        {self ? (
                          <Badge tone="info" className="capitalize">{u.role}</Badge>
                        ) : (
                          <Select aria-label={`Role for ${u.email}`} value={u.role} onChange={(e) => changeRole(u, e.target.value as "admin" | "analyst")} className="h-8 w-28 text-xs" disabled={!u.is_active}>
                            <option value="analyst">Analyst</option>
                            <option value="admin">Admin</option>
                          </Select>
                        )}
                      </Td>
                      <Td className="hidden sm:table-cell">
                        {!u.is_active ? <Badge>Deactivated</Badge> : u.must_change_password ? <Badge tone="warn">Invite pending</Badge> : <Badge tone="pass">Active</Badge>}
                      </Td>
                      <Td className="hidden text-muted md:table-cell">{u.last_login_at ? ago(u.last_login_at) : "Never"}</Td>
                      <Td align="right">
                        <RowMenu u={u} self={self} onAction={(action) => setPending({ u, action })} />
                      </Td>
                    </tr>
                  );
                })}
              </tbody>
            </Table>
          )}
        </Card>

        <Card title={<span className="flex items-center gap-2"><Users size={15} aria-hidden /> Roles</span>}>
          <dl className="space-y-4 text-sm">
            <div>
              <dt className="font-medium">Analyst</dt>
              <dd className="mt-1 text-muted">Researches stocks, runs analyses, proposes trades and can halt trading with the kill switch.</dd>
            </div>
            <div>
              <dt className="font-medium">Admin</dt>
              <dd className="mt-1 text-muted">Everything an analyst can do, plus approving paper orders, resuming trading, managing data, models and users.</dd>
            </div>
          </dl>
          <p className="mt-5 border-t border-line pt-4 text-xs text-subtle">
            Changing a role, resetting a password or deactivating someone signs out all of their sessions immediately. The last active admin can never be removed.
          </p>
        </Card>
      </div>

      <Dialog
        open={inviteOpen}
        onClose={() => setInviteOpen(false)}
        title="Invite a user"
        description="Aegis creates the account with a one-time temporary password for you to share privately."
        footer={
          <>
            <Button onClick={() => setInviteOpen(false)} disabled={busy}>Cancel</Button>
            <Button variant="primary" type="submit" form="invite-form" loading={busy} disabled={!/.+@.+\..+/.test(email)}>Create invite</Button>
          </>
        }
      >
        <form id="invite-form" onSubmit={invite} className="space-y-4">
          <Field label="Email">{(id) => <Input id={id} type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="colleague@example.com" required />}</Field>
          <Field label="Role">
            {(id) => (
              <Select id={id} value={role} onChange={(e) => setRole(e.target.value as "analyst" | "admin")}>
                <option value="analyst">Analyst</option>
                <option value="admin">Admin</option>
              </Select>
            )}
          </Field>
        </form>
      </Dialog>

      <Dialog
        open={secret !== null}
        onClose={() => setSecret(null)}
        title={secret?.title ?? ""}
        description="Send these sign-in details privately (not by public chat). The password is shown only this once."
        footer={<Button variant="primary" onClick={() => setSecret(null)}>Done</Button>}
      >
        {secret && (
          <div className="space-y-4">
            <div>
              <p className="mb-1.5 text-xs font-medium text-muted">Sign-in email</p>
              <CopyField value={secret.result.user.email} />
            </div>
            <div>
              <p className="mb-1.5 text-xs font-medium text-muted">Temporary password</p>
              <CopyField value={secret.result.temporary_password} />
            </div>
            <Callout tone="info">They&apos;ll be asked to choose their own password at first sign-in.</Callout>
          </div>
        )}
      </Dialog>

      <ConfirmDialog
        open={pending !== null}
        onClose={() => !busy && setPending(null)}
        onConfirm={confirmAction}
        busy={busy}
        tone={pending?.action === "toggle" && pending.u.is_active ? "danger" : "primary"}
        title={
          pending?.action === "reset"
            ? `Reset the password for ${pending.u.email}?`
            : pending?.u.is_active
              ? `Deactivate ${pending?.u.email}?`
              : `Reactivate ${pending?.u.email}?`
        }
        body={
          pending?.action === "reset"
            ? "Their current password stops working and they're signed out. You'll get a new temporary password to share."
            : pending?.u.is_active
              ? "They're signed out immediately and can't sign in until reactivated. Their history is kept."
              : "They'll be able to sign in again with their existing password."
        }
        confirmLabel={pending?.action === "reset" ? "Reset password" : pending?.u.is_active ? "Deactivate" : "Reactivate"}
      />
    </div>
  );
}
