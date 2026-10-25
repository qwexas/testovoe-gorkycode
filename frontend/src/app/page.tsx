import { AppHeader } from "@/components/app-header";
import { ServerStatus } from "@/components/server-status";
import { MAIN_CONTENT_ID, SkipLink } from "@/components/skip-link";
import { ThemeSwitcher } from "@/components/theme-switcher";
import { AssistantStage } from "@/features/assistant/components/assistant-stage";
import { DayFeed } from "@/features/events/components/day-feed";
import { ProfileMenu } from "@/features/profile/components/profile-menu";
import { ProfileNotice } from "@/features/profile/components/profile-notice";
import { ProfileProvider } from "@/features/profile/profile-context";

export default function HomePage() {
  return (
    <ProfileProvider>
      <SkipLink />
      <AppHeader
        actions={
          <>
            <ServerStatus />
            <ThemeSwitcher />
            <ProfileMenu />
          </>
        }
      />
      <main
        id={MAIN_CONTENT_ID}
        tabIndex={-1}
        className="mx-auto grid w-full max-w-6xl flex-1 gap-4 px-4 py-4 outline-none sm:gap-6 sm:px-6 sm:py-6 lg:grid-cols-[minmax(0,1fr)_20rem]"
      >
        <div className="flex min-w-0 flex-col gap-4 sm:gap-6">
          <ProfileNotice />
          <AssistantStage />
        </div>
        <DayFeed />
      </main>
    </ProfileProvider>
  );
}
