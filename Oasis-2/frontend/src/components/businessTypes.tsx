import {
  BedDouble,
  Bike,
  Briefcase,
  Coffee,
  Compass,
  Dumbbell,
  Globe,
  GraduationCap,
  Hotel,
  Scissors,
  ShoppingBag,
  Stethoscope,
  Store,
  Ticket,
  UtensilsCrossed,
  Wine,
  Wrench,
} from "lucide-react";
import type { BusinessType } from "../types";

// Keep in sync with backend/app/categories.py.
export const BUSINESS_TYPES: { value: BusinessType; label: string; examples: string; icon: typeof Store; placeholder: string }[] = [
  { value: "shop", label: "Shop or retail", examples: "bookshop, bakery counter, florist, boutique", icon: ShoppingBag, placeholder: "Buchhandlung am Rhein" },
  { value: "beauty", label: "Hair, beauty or spa", examples: "hairdresser, barber, nails, massage", icon: Scissors, placeholder: "Salon Lina" },
  { value: "health", label: "Doctor, dentist or therapist", examples: "GP, dentist, physio, vet", icon: Stethoscope, placeholder: "Praxis Dr. Keller" },
  { value: "fitness", label: "Gym, studio or sports", examples: "gym, yoga, climbing, tennis club", icon: Dumbbell, placeholder: "Studio Move" },
  { value: "services", label: "Home or local services", examples: "plumber, electrician, cleaner, repairs", icon: Wrench, placeholder: "Meier Plumbing" },
  { value: "professional", label: "Lawyer, accountant or agency", examples: "law firm, tax advisor, architect, agency", icon: Briefcase, placeholder: "Huber & Partner" },
  { value: "education", label: "School, courses or tutoring", examples: "language school, music lessons, driving school", icon: GraduationCap, placeholder: "Basel Language School" },
  { value: "restaurant", label: "Restaurant", examples: "restaurant, takeaway, pizzeria", icon: UtensilsCrossed, placeholder: "Restaurant Rheinblick" },
  { value: "cafe", label: "Café or bakery", examples: "café, bakery, ice cream", icon: Coffee, placeholder: "Café Mittlere" },
  { value: "bar", label: "Bar or club", examples: "bar, pub, wine bar, club", icon: Wine, placeholder: "Bar Rhywälle" },
  { value: "hotel", label: "Hotel or B&B", examples: "hotel, guesthouse, B&B", icon: Hotel, placeholder: "Hotel Krafft" },
  { value: "hostel", label: "Hostel or holiday rental", examples: "hostel, apartment, campsite", icon: BedDouble, placeholder: "Basel Backpack" },
  { value: "activities", label: "Tours, activities or attractions", examples: "city tours, museum, escape room", icon: Compass, placeholder: "Rhine Boat Tours" },
  { value: "events", label: "Events, venue or tickets", examples: "theatre, concerts, event space", icon: Ticket, placeholder: "Kaserne Basel" },
  { value: "rental", label: "Rentals", examples: "bikes, cars, equipment, costumes", icon: Bike, placeholder: "Velo Rent Basel" },
  { value: "online", label: "Online business or any website", examples: "web shop, SaaS, online courses, blog", icon: Globe, placeholder: "Your online shop" },
  { value: "other", label: "Something else", examples: "describe it in your own words below", icon: Store, placeholder: "Your business name" },
];

export function typeInfo(type: BusinessType) {
  return BUSINESS_TYPES.find((t) => t.value === type) ?? BUSINESS_TYPES[BUSINESS_TYPES.length - 1];
}

/** How to show a business's kind: the owner's own words win over the category name. */
export function kindLabel(type: BusinessType, own?: string): string {
  return own?.trim() || typeInfo(type).label;
}
