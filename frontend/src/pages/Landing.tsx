import { Navbar } from "@/components/landing/Navbar"
import { Hero } from "@/components/landing/Hero"
import { Trust } from "@/components/landing/Trust"
import { Features } from "@/components/landing/Features"
import { DashboardPreview } from "@/components/landing/DashboardPreview"
import { Workflow } from "@/components/landing/Workflow"
import { Benefits } from "@/components/landing/Benefits"
import { FAQ } from "@/components/landing/FAQ"
import { Footer } from "@/components/landing/Footer"

/**
 * The marketing page is designed as a cinematic dark canvas regardless of
 * the console theme: `.theme-dark` re-declares every design token for this
 * subtree (see index.css), so the shared components render on dark here
 * while the signed-in console follows the user's light/dark preference.
 */
export default function LandingPage() {
  return (
    <div className="theme-dark relative min-h-screen overflow-x-clip bg-[#0f131a] text-slate-100">
      <Navbar />
      <main>
        <Hero />
        <Trust />
        <Features />
        <DashboardPreview />
        <Workflow />
        <Benefits />
        <FAQ />
      </main>
      <Footer />
    </div>
  )
}
