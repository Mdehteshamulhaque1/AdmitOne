import { Navigate, useNavigate } from "react-router-dom"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { Rocket, Sparkles } from "lucide-react"
import { toast } from "sonner"
import { Background } from "@/components/background"
import { LogoWordmark } from "@/components/logo"
import { Button } from "@/components/ui/Button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/Card"
import { Input } from "@/components/ui/Input"
import { Label } from "@/components/ui/Label"
import { PageLoader } from "@/components/widgets/PageLoader"
import { useAuth } from "@/lib/auth"
import { useCreateOrganization } from "@/lib/queries"
import { formatApiError } from "@/lib/types"

const createSchema = z.object({
  name: z.string().min(2, "Workspace name is required"),
  tagline: z.string().optional().default(""),
  city: z.string().optional().default(""),
  country: z.string().optional().default(""),
  building_name: z.string().optional().default(""),
})
type CreateValues = z.infer<typeof createSchema>

export function OnboardingPage() {
  const { isAuthenticated, loading, org, refreshUser, logout } = useAuth()
  const navigate = useNavigate()
  const createOrg = useCreateOrganization()

  const createForm = useForm<CreateValues>({
    resolver: zodResolver(createSchema),
    defaultValues: { name: "", tagline: "", city: "", country: "", building_name: "" },
  })

  if (loading) return <PageLoader />
  if (!isAuthenticated) return <Navigate to="/login" replace />
  if (org) return <Navigate to="/dashboard" replace />

  const onCreate = async (values: CreateValues) => {
    try {
      await createOrg.mutateAsync({
        ...values,
        tagline: values.tagline || undefined,
        city: values.city || undefined,
        country: values.country || undefined,
        building_name: values.building_name || undefined,
      })
      await refreshUser()
      toast.success("Workspace created", {
        description: `Welcome to ${values.name}. Start by registering a visitor.`,
      })
      navigate("/dashboard", { replace: true })
    } catch (err) {
      toast.error(formatApiError(err))
    }
  }

  return (
    <div className="flex min-h-screen">
      <Background />
      <div className="mx-auto flex w-full max-w-xl flex-col justify-center px-6 py-12 sm:px-0">
        <div className="mb-10 flex items-center justify-between">
          <LogoWordmark />
          <Button variant="ghost" size="sm" onClick={() => { logout(); navigate("/login", { replace: true }) }}>
            Sign out
          </Button>
        </div>

        <div className="mb-8">
          <h2 className="text-2xl font-bold tracking-tight">Set up your workspace</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            SecureGate needs a workspace to scope visitors, buildings and approvals.
          </p>
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Rocket className="size-4 text-primary" /> Start fresh
            </CardTitle>
            <CardDescription>
              You'll become the workspace admin. A default building is created so you can register
              visitors right away.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={createForm.handleSubmit(onCreate)} className="space-y-4" noValidate>
              <div className="space-y-1.5">
                <Label htmlFor="org_name">Workspace name</Label>
                <Input id="org_name" placeholder="Enter your workspace name" {...createForm.register("name")} />
                {createForm.formState.errors.name && (
                  <p className="text-xs text-danger">{createForm.formState.errors.name.message}</p>
                )}
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor="building_name">Default building</Label>
                  <Input id="building_name" placeholder="e.g. Main office" {...createForm.register("building_name")} />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="tagline">Tagline (optional)</Label>
                  <Input id="tagline" placeholder="Optional short tagline" {...createForm.register("tagline")} />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="city">City (optional)</Label>
                  <Input id="city" placeholder="Your city" {...createForm.register("city")} />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="country">Country (optional)</Label>
                  <Input id="country" placeholder="Your country" {...createForm.register("country")} />
                </div>
              </div>
              <Button
                type="submit"
                className="w-full gap-2"
                size="lg"
                loading={createForm.formState.isSubmitting || createOrg.isPending}
              >
                <Sparkles className="size-4" />
                {createOrg.isPending ? "Creating workspace…" : "Create workspace"}
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}