import { ConsoleScreen } from "@/features/console/components/console-screen";
import { ProfileProvider } from "@/features/profile/profile-context";

/** Главный экран: сессия «Консоли» поверх анонимного профиля. */
export default function HomePage() {
  return (
    <ProfileProvider>
      <ConsoleScreen />
    </ProfileProvider>
  );
}
