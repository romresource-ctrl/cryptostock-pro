// @ts-nocheck
import { ScrollViewStyleReset } from "expo-router/html";
import type { PropsWithChildren } from "react";

/**
 * v8.12.45 — HTML root with an instant splash screen.
 *
 * The Expo Router web bundle takes ~3-5 seconds to hydrate on first
 * paint. During that window the page is otherwise a black rectangle,
 * which is what contest / gallery snapshot systems capture. To fix
 * that we ship a lightweight inline splash rendered directly in the
 * HTML shell so it appears on the very first paint — before any JS
 * has even downloaded. Once React mounts and paints into `#root`,
 * we hide the splash so nothing overlaps the real UI.
 */
export default function Root({ children }: PropsWithChildren) {
  return (
    <html lang="en" style={{ height: "100%" }}>
      <head>
        <meta charSet="utf-8" />
        <meta httpEquiv="X-UA-Compatible" content="IE=edge" />
        <meta
          name="viewport"
          content="width=device-width, initial-scale=1, shrink-to-fit=no"
        />
        <meta name="description" content="AI Crypto Stock Pro — AI trading signals for crypto, stocks, ETFs, gold, forex. 27+ premium picks with live win-rate tracking." />
        <meta name="theme-color" content="#0B0E11" />
        {/*
          Disable body scrolling on web to make ScrollView components work correctly.
          If you want to enable scrolling, remove `ScrollViewStyleReset` and
          set `overflow: auto` on the body style below.
        */}
        <ScrollViewStyleReset />
        <style
          dangerouslySetInnerHTML={{
            __html: `
              html, body {
                background: #0B0E11;
              }
              body > div:first-child { position: fixed !important; top: 0; left: 0; right: 0; bottom: 0; }
              [role="tablist"] [role="tab"] * { overflow: visible !important; }
              [role="heading"], [role="heading"] * { overflow: visible !important; }

              /* v8.12.45 — Instant splash: renders on first HTML paint,
                 disappears the moment #root has any painted children
                 (which is what Metro hydration produces). Snapshot
                 services get a branded frame instead of a black square. */
              #ai-splash {
                position: fixed;
                inset: 0;
                z-index: 999999;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                background: linear-gradient(160deg, #0B0E11 0%, #12181F 45%, #0B0E11 100%);
                color: #F5F7FA;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                gap: 18px;
                padding: 24px;
                text-align: center;
                pointer-events: none;
                animation: aiSplashFade 0.35s ease-out 3.5s forwards;
              }
              @keyframes aiSplashFade {
                to { opacity: 0; visibility: hidden; }
              }
              #ai-splash .logo {
                width: 72px;
                height: 72px;
                border-radius: 20px;
                background: linear-gradient(135deg, #F0B90B 0%, #F97316 100%);
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 34px;
                font-weight: 900;
                color: #0B0E11;
                letter-spacing: -1.5px;
                box-shadow: 0 12px 28px rgba(240,185,11,0.28);
              }
              #ai-splash h1 {
                margin: 0;
                font-size: 22px;
                font-weight: 900;
                letter-spacing: 0.4px;
                color: #F5F7FA;
              }
              #ai-splash h1 .accent { color: #F0B90B; }
              #ai-splash .tagline {
                margin: 0;
                font-size: 12px;
                color: #94A3B8;
                letter-spacing: 0.4px;
                text-transform: uppercase;
                font-weight: 700;
              }
              #ai-splash .chips {
                display: flex;
                gap: 6px;
                flex-wrap: wrap;
                justify-content: center;
                max-width: 320px;
                margin-top: 4px;
              }
              #ai-splash .chip {
                padding: 4px 10px;
                border-radius: 999px;
                border: 1px solid #1F2937;
                background: rgba(15,23,42,0.65);
                font-size: 10.5px;
                color: #CBD5E1;
                letter-spacing: 0.3px;
                font-weight: 700;
              }
              #ai-splash .spinner {
                margin-top: 4px;
                width: 24px;
                height: 24px;
                border-radius: 50%;
                border: 3px solid rgba(240,185,11,0.18);
                border-top-color: #F0B90B;
                animation: aiSpin 0.9s linear infinite;
              }
              @keyframes aiSpin { to { transform: rotate(360deg); } }
            `,
          }}
        />
      </head>
      <body
        style={{
          margin: 0,
          height: "100%",
          overflow: "hidden",
          display: "flex",
          flexDirection: "column",
          backgroundColor: "#0B0E11",
        }}
      >
        {/* v8.12.45 — Static splash rendered on first HTML paint. It's a
             pure HTML/CSS artefact so snapshot services capture it before
             the JS bundle finishes hydrating. Fades out automatically at
             3.5s (see @keyframes aiSplashFade), well after the React
             tree has mounted. */}
        <div id="ai-splash" aria-hidden="true">
          <div className="logo">A₿</div>
          <h1>AI <span className="accent">Crypto Stock</span> Pro</h1>
          <p className="tagline">AI Trading Signals · Live Win-Rate</p>
          <div className="chips">
            <span className="chip">Crypto</span>
            <span className="chip">Stocks</span>
            <span className="chip">ETF</span>
            <span className="chip">Gold</span>
            <span className="chip">Forex</span>
          </div>
          <div className="spinner" />
        </div>
        {children}
      </body>
    </html>
  );
}
