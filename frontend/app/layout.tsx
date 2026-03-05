import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { Sidebar } from "@/components/layout/sidebar";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "AI 자동 채점 파이프라인",
  description: "LangGraph 기반 AI 채점 + 교사 HITL 검수 시스템",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko">
      <body className={`${geistSans.variable} ${geistMono.variable} antialiased`}>
        <div className="flex min-h-screen">
          {/* 고정 사이드바 */}
          <Sidebar />
          {/* 메인 콘텐츠 — 사이드바 너비만큼 왼쪽 여백 */}
          <main className="ml-56 flex-1 min-h-screen bg-muted/30">
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}
