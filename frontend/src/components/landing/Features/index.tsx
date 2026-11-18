import { motion } from "framer-motion"
import {
  Ban,
  CheckCheck,
  Database,
  KeyRound,
  Lock,
  Mail,
  QrCode,
  ScanLine,
  ScrollText,
  ShieldCheck,
  Users,
  type LucideIcon,
} from "lucide-react"
import { Container, Section } from "@/components/landing/Section"
import { SectionHeading } from "@/components/landing/SectionHeading"
import { FEATURES } from "@/components/landing/lib"
import { fadeUp } from "@/components/landing/motion"

const ICONS: Record<string, LucideIcon> = {
  "Organization-based data isolation": Database,
  "Three roles: ADMIN, RECEPTIONIST and SECURITY": Users,
  "Role-based permission checks": ShieldCheck,
  "Login failure tracking and account lockout": Lock,
  "Transaction-based visit approval and rejection": CheckCheck,
  "HMAC-SHA256 signed QR passes": KeyRound,
  "Single-use QR verification": QrCode,
  "Database locking and conditional updates to prevent duplicate QR check-ins": ScanLine,
  "Blacklisted visitor restrictions": Ban,
  "Audit logging": ScrollText,
  "QR email delivery": Mail,
}

export function Features() {
  return (
    <Section id="features" className="py-24 lg:py-32">
      <Container>
        <SectionHeading
          eyebrow="Everything you need"
          title="One platform. Every gate, desk and lobby."
          description="AdmitOne replaces paper registers, reception spreadsheets and scattered tools with a single, elegant system your whole company will actually use."
        />

        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3 lg:gap-6">
          {FEATURES.map((feature, i) => {
            const Icon = ICONS[feature.title]
            return (
              <motion.article
                key={feature.title}
                variants={fadeUp}
                initial="hidden"
                whileInView="show"
                viewport={{ once: true, margin: "-60px" }}
                transition={{ delay: (i % 3) * 0.08 }}
                className="glow-border glass-card group relative overflow-hidden rounded-2xl p-7"
              >
                <div
                  aria-hidden="true"
                  className="pointer-events-none absolute -right-16 -top-16 size-40 rounded-full opacity-0 blur-[60px] transition-opacity duration-500 group-hover:opacity-100"
                  style={{ background: `${feature.accent}33` }}
                />
                <div className="flex items-center justify-between">
                  <span
                    className="relative flex size-12 items-center justify-center rounded-xl border transition-transform duration-300 group-hover:scale-110 group-hover:-rotate-3"
                    style={{
                      color: feature.accent,
                      background: `${feature.accent}14`,
                      borderColor: `${feature.accent}38`,
                    }}
                  >
                    <Icon className="size-5.5" strokeWidth={1.8} />
                  </span>
                  <span className="text-xs font-medium tabular-nums text-muted-foreground/60">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                </div>
                <h3 className="mt-6 text-lg font-semibold tracking-tight">{feature.title}</h3>
                <p className="mt-2.5 text-sm leading-relaxed text-muted-foreground">
                  {feature.description}
                </p>
              </motion.article>
            )
          })}
        </div>
      </Container>
    </Section>
  )
}
