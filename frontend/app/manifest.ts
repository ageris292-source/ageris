import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Aegis — research & paper trading",
    short_name: "Aegis",
    description: "Multi-agent research, backtesting and risk-gated paper trading for NSE & BSE equities.",
    start_url: "/",
    scope: "/",
    display: "standalone",
    background_color: "#0d0d0d",
    theme_color: "#0d0d0d",
    categories: ["finance", "productivity"],
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icons/maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
    shortcuts: [
      { name: "Stocks", url: "/stocks", icons: [{ src: "/icons/icon-192.png", sizes: "192x192" }] },
      { name: "Opportunities", url: "/ranking", icons: [{ src: "/icons/icon-192.png", sizes: "192x192" }] },
      { name: "Paper trading", url: "/paper", icons: [{ src: "/icons/icon-192.png", sizes: "192x192" }] },
    ],
  };
}
