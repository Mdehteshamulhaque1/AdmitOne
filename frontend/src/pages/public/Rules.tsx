import { useEffect, type ReactNode } from "react"
import { Link, useLocation } from "react-router-dom"
import { Camera, DoorOpen, IdCard, ScrollText } from "lucide-react"
import { PublicLayout } from "@/components/public/PublicNav"
import { ID_PROOFS } from "@/components/visitor/booking"

function RuleSection({ id, icon, title, children }: { id: string; icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <section id={id} className="scroll-mt-24 rounded-2xl border border-border bg-card p-5 shadow-card sm:p-6">
      <h2 className="flex items-center gap-2.5 text-lg font-semibold tracking-tight">
        <span className="flex size-9 items-center justify-center rounded-lg bg-primary-soft text-primary">{icon}</span>
        {title}
      </h2>
      <ol className="mt-4 list-decimal space-y-2 pl-5 text-sm leading-relaxed text-muted-foreground marker:font-semibold marker:text-foreground">{children}</ol>
    </section>
  )
}

export function RulesPage() {
  const { hash } = useLocation()
  useEffect(() => {
    if (hash) document.getElementById(hash.slice(1))?.scrollIntoView({ behavior: "smooth" })
  }, [hash])

  return (
    <PublicLayout>
      <div className="max-w-3xl">
        <h1 className="text-3xl font-semibold tracking-tight">Rules and guidelines</h1>
        <p className="mt-2 text-muted-foreground">Please read these before applying for a visitor pass. Entry can be refused if they aren't followed.</p>

        <div className="mt-8 space-y-5">
          <RuleSection id="pass" icon={<ScrollText className="size-4" />} title="Visitor pass rules">
            <li>Visitors apply online through <Link to="/visitor" className="font-medium text-primary hover:underline">Apply for a visitor pass</Link>. Walk-in visitors are registered at reception.</li>
            <li>The person you are meeting approves the request. You can track the status under My visits.</li>
            <li>The QR pass is issued only after approval and is sent by email and shown under My visits.</li>
            <li>A pass is valid only for the date and time slot shown on it, and can be used once.</li>
            <li>The pass is personal and can't be transferred to anyone else.</li>
            <li>To change your time, reschedule from My visits; don't book a second visit for the same purpose.</li>
          </RuleSection>

          <RuleSection id="id" icon={<IdCard className="size-4" />} title="Identity proof">
            <li>Enter one identity proof when you apply: {ID_PROOFS.map((p) => p.label).join(", ")}.</li>
            <li>Bring the ORIGINAL of the same identity proof to the gate. Photocopies and photos on a phone aren't accepted.</li>
            <li>The name on the ID must match the name on your visitor account.</li>
            <li>Your ID number is visible only to authorised staff, and only its last 4 characters appear on screens.</li>
          </RuleSection>

          <RuleSection id="photo" icon={<Camera className="size-4" />} title="Photo guidelines">
            <li>Use a recent, clear photo of your face, looking at the camera.</li>
            <li>No caps, sunglasses or masks; use plain light and a plain background.</li>
            <li>JPG or PNG. On a phone you can take the photo directly from the form.</li>
            <li>Reception compares your face with this photo at the gate.</li>
          </RuleSection>

          <RuleSection id="gate" icon={<DoorOpen className="size-4" />} title="At the gate">
            <li>Arrive a few minutes before your time slot with your QR pass and original ID.</li>
            <li>Security scans the pass; it can't be used again after entry.</li>
            <li>Reception gives you your room on approval; it's shown on your pass.</li>
            <li>Follow security instructions on site and check out at the gate when you leave.</li>
          </RuleSection>
        </div>
      </div>
    </PublicLayout>
  )
}
