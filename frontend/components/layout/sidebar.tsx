"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  {
    href: "/setup",
    label: "문항 및 루브릭 세팅",
    icon: "📋",
  },
  {
    href: "/grading",
    label: "학생 답안 검수",
    icon: "✅",
  },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="fixed left-0 top-0 h-full w-56 border-r bg-background flex flex-col">
      {/* 로고 */}
      <div className="px-4 py-5 border-b">
        <h1 className="text-sm font-bold leading-tight text-foreground">
          AI 자동 채점
          <br />
          파이프라인
        </h1>
      </div>

      {/* 네비게이션 */}
      <nav className="flex-1 py-4 px-2 space-y-1">
        {NAV_ITEMS.map((item) => {
          const isActive = pathname.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-2.5 rounded-md px-3 py-2.5 text-sm font-medium transition-colors",
                isActive
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
              )}
            >
              <span>{item.icon}</span>
              <span className="leading-tight">{item.label}</span>
            </Link>
          );
        })}
      </nav>

      {/* 하단 정보 */}
      <div className="px-4 py-3 border-t">
        <p className="text-xs text-muted-foreground">powered by Claude</p>
      </div>
    </aside>
  );
}
