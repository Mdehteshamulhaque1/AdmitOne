/**
 * Dropdown option sets for the visitor profile (training-centre scenario).
 *
 * These are presentation defaults only: the API stores free text, so a
 * visitor can always pick "Other" and type their own value, and a workspace
 * can change its *categories and purposes* in Settings (the catalogue). The
 * lists here are the ones every workspace shares: Indian states, common
 * qualifications and well-known universities.
 */

export interface Option {
  value: string
  label: string
}

export const OTHER_VALUE = "__other__"

/** Mirrors the backend's default catalogue keys (visits/purposes.py). */
export const DEFAULT_VISITOR_CATEGORIES: Option[] = [
  { value: "STUDENT", label: "Student / trainee" },
  { value: "PARENT", label: "Parent / guardian" },
  { value: "RECRUITER", label: "Recruiter / company" },
  { value: "VENDOR", label: "Vendor / delivery" },
  { value: "OTHER", label: "Other" },
]

export const INDIAN_STATES: string[] = [
  "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat",
  "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh",
  "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan",
  "Sikkim", "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal",
  "Andaman and Nicobar Islands", "Chandigarh", "Dadra and Nagar Haveli and Daman and Diu",
  "Delhi", "Jammu and Kashmir", "Ladakh", "Lakshadweep", "Puducherry",
]

export const QUALIFICATIONS: string[] = [
  "B.Tech / B.E. (CSE / IT)",
  "B.Tech / B.E. (ECE / EEE)",
  "B.Tech / B.E. (Mechanical / Civil / other)",
  "M.Tech / M.E.",
  "BCA",
  "MCA",
  "B.Sc (Computer Science / IT)",
  "B.Sc (other)",
  "M.Sc",
  "B.Com",
  "M.Com",
  "BBA",
  "MBA",
  "B.A.",
  "M.A.",
  "Diploma (Engineering)",
  "Diploma (other)",
  "12th / Intermediate",
  "Ph.D.",
]

export const UNIVERSITIES: string[] = [
  "Dr. A.P.J. Abdul Kalam Technical University (AKTU), Lucknow",
  "Delhi University",
  "Guru Gobind Singh Indraprastha University (GGSIPU), Delhi",
  "Jamia Millia Islamia, Delhi",
  "Jawaharlal Nehru University (JNU), Delhi",
  "Amity University, Noida",
  "Sharda University, Greater Noida",
  "Galgotias University, Greater Noida",
  "Gautam Buddha University, Greater Noida",
  "Chaudhary Charan Singh University, Meerut",
  "Maharshi Dayanand University (MDU), Rohtak",
  "Kurukshetra University",
  "Chandigarh University",
  "Lovely Professional University (LPU), Punjab",
  "Punjab Technical University (IKGPTU)",
  "Rajasthan Technical University (RTU), Kota",
  "University of Rajasthan, Jaipur",
  "Rajiv Gandhi Proudyogiki Vishwavidyalaya (RGPV), Bhopal",
  "Devi Ahilya Vishwavidyalaya (DAVV), Indore",
  "Aryabhatta Knowledge University, Patna",
  "Patna University",
  "Magadh University, Bodh Gaya",
  "Lalit Narayan Mithila University, Darbhanga",
  "Ranchi University",
  "Birsa Institute of Technology (BIT), Sindri",
  "Biju Patnaik University of Technology (BPUT), Odisha",
  "Utkal University, Bhubaneswar",
  "Maulana Abul Kalam Azad University of Technology (MAKAUT), West Bengal",
  "University of Calcutta",
  "Gauhati University",
  "Dibrugarh University",
  "Uttarakhand Technical University, Dehradun",
  "Graphic Era University, Dehradun",
  "Himachal Pradesh Technical University",
  "University of Jammu",
  "University of Kashmir",
  "Gujarat Technological University (GTU)",
  "Savitribai Phule Pune University",
  "University of Mumbai",
  "Visvesvaraya Technological University (VTU), Karnataka",
  "Bangalore University",
  "Anna University, Chennai",
  "Jawaharlal Nehru Technological University (JNTU), Hyderabad",
  "Osmania University, Hyderabad",
  "Andhra University",
  "APJ Abdul Kalam Technological University (KTU), Kerala",
  "University of Kerala",
  "Chhattisgarh Swami Vivekanand Technical University (CSVTU)",
  "Indira Gandhi National Open University (IGNOU)",
]

const THIS_YEAR = new Date().getFullYear()

/** Next year (final-year students) back 15 years. */
export const PASSING_YEARS: number[] = Array.from({ length: 17 }, (_, i) => THIS_YEAR + 1 - i)

export const toOptions = (values: readonly string[]): Option[] => values.map((v) => ({ value: v, label: v }))

/** Pretty label for a category key, using the default list as a fallback. */
export function categoryLabel(key: string, catalogue?: { key: string; label: string }[]): string {
  const k = (key || "").toUpperCase()
  if (!k) return ""
  return (
    catalogue?.find((c) => c.key === k)?.label ??
    DEFAULT_VISITOR_CATEGORIES.find((c) => c.value === k)?.label ??
    k.charAt(0) + k.slice(1).toLowerCase().replace(/_/g, " ")
  )
}
