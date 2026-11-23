import { Link } from "react-router-dom"
import { ArrowRight, CalendarCheck2, CheckCheck, ClipboardX, QrCode, ScanLine, ShieldCheck, UserPlus, Users, type LucideIcon } from "lucide-react"
import { Logo } from "@/components/logo"
import { PublicNav } from "@/components/public/PublicNav"
import { cn } from "@/lib/utils"

function Point({ icon: Icon, children, dark }: { icon: LucideIcon; children: React.ReactNode; dark?: boolean }) {
  return (
    <li className="flex items-center gap-2.5">
      <Icon className={cn("size-4 shrink-0", dark ? "text-nav-accent" : "text-primary")} />
      <span>{children}</span>
    </li>
  )
}

/**
 * The front door: visitors and staff each have their own portal on the same
 * backend. Visitors book and keep their pass; staff run the console.
 */
export function PortalChooserPage() {
  return (
    <div className="flex min-h-screen flex-col bg-background">
      <PublicNav />

      <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col justify-center px-4 pb-16 pt-6 sm:px-6">
        <div className="max-w-xl">
          <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">Welcome to AdmitOne</h1>
          <p className="mt-2 text-base text-muted-foreground">Choose how you're using AdmitOne today.</p>
        </div>

        <div className="mt-8 grid gap-5 md:grid-cols-2">
          <Link
            to="/visitor"
            className="group flex flex-col rounded-2xl border border-border bg-card p-6 shadow-card transition hover:border-primary/60 hover:shadow-lift focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:p-7"
          >
            <span className="flex size-11 items-center justify-center rounded-xl bg-primary-soft text-primary">
              <CalendarCheck2 className="size-5" />
            </span>
            <h2 className="mt-5 text-xl font-semibold tracking-tight">I'm a visitor</h2>
            <p className="mt-1 text-sm text-muted-foreground">Book a visit with someone here and keep your entry pass on your phone.</p>
            <ul className="mt-5 space-y-2.5 text-sm">
              <Point icon={CalendarCheck2}>Pick a purpose, a person and a time</Point>
              <Point icon={CheckCheck}>See when your host approves</Point>
              <Point icon={QrCode}>Show your QR pass at the gate</Point>
            </ul>
            <span className="mt-7 inline-flex items-center gap-2 text-sm font-semibold text-primary">
              Continue as visitor <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" />
            </span>
          </Link>

          <Link
            to="/admin"
            className="group flex flex-col rounded-2xl bg-nav p-6 text-nav-foreground shadow-card transition hover:shadow-lift focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:p-7"
          >
            <span className="flex size-11 items-center justify-center rounded-xl bg-nav-active text-nav-accent">
              <Logo size={24} />
            </span>
            <h2 className="mt-5 text-xl font-semibold tracking-tight">Admin and staff</h2>
            <p className="mt-1 text-sm text-nav-muted">Run reception and the gate for your organisation.</p>
            <ul className="mt-5 space-y-2.5 text-sm">
              <Point icon={CheckCheck} dark>Approve visit requests</Point>
              <Point icon={UserPlus} dark>Register walk-in visitors</Point>
              <Point icon={ScanLine} dark>Scan passes and see who's inside</Point>
            </ul>
            <span className="mt-7 inline-flex items-center gap-2 text-sm font-semibold text-nav-accent">
              Sign in to the console <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" />
            </span>
          </Link>
        </div>

        <section aria-labelledby="why-title" className="mt-14 border-t border-border pt-10">
          <h2 id="why-title" className="text-xl font-semibold tracking-tight">Why AdmitOne</h2>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            Most gates still run on a paper register: a queue at the counter, handwriting nobody can read, a phone call to find the host, and no reliable list of who is inside.
          </p>
          <div className="mt-6 grid gap-5 md:grid-cols-3">
            {[
              {
                icon: ClipboardX,
                title: "The problem it solves",
                points: [
                  "Long queues while visitors fill in a register",
                  "Passes that can be copied, forwarded or reused",
                  "No live count of who is inside during an emergency",
                ],
              },
              {
                icon: ShieldCheck,
                title: "What makes it different",
                points: [
                  "The person you're meeting approves before you travel",
                  "Each QR pass is signed, works once and only for its time slot",
                  "Photo and ID proof are matched at the gate, and every action is logged",
                ],
              },
              {
                icon: Users,
                title: "Why people use it",
                points: [
                  "Visitors book from a phone in about 3 minutes, no queue",
                  "Reception approves, assigns the room and scans in seconds",
                  "Admins get a live inside-now list, reports and an audit trail",
                ],
              },
            ].map((col) => (
              <div key={col.title} className="rounded-2xl border border-border bg-card p-5">
                <col.icon className="size-5 text-primary" />
                <h3 className="mt-3 text-sm font-semibold">{col.title}</h3>
                <ul className="mt-2 space-y-1.5 text-sm text-muted-foreground">
                  {col.points.map((p) => (
                    <li key={p} className="flex gap-2"><span aria-hidden="true" className="mt-2 size-1 shrink-0 rounded-full bg-primary" />{p}</li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
          <p className="mt-6 text-sm text-muted-foreground">
            Want the full tour? <Link to="/about" className="font-medium text-primary hover:underline">See how it works</Link>.
          </p>
        </section>
      </main>
    </div>
  )
}
