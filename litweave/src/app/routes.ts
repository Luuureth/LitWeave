import { createBrowserRouter } from "react-router";
import { RootLayout } from "./layouts/RootLayout";
import { Home } from "./pages/Home";
import { Events } from "./pages/Events";
import { EventDetail } from "./pages/EventDetail";
import { Characters } from "./pages/Characters";
import { CharacterDetail } from "./pages/CharacterDetail";
import { Locations } from "./pages/Locations";
import { LocationDetail } from "./pages/LocationDetail";

export const router = createBrowserRouter([
  {
    path: "/",
    Component: RootLayout,
    children: [
      { index: true, Component: Home },
      { path: "events", Component: Events },
      { path: "events/:linkId", Component: EventDetail },
      { path: "characters", Component: Characters },
      { path: "characters/:name", Component: CharacterDetail },
      { path: "locations", Component: Locations },
      { path: "locations/:name", Component: LocationDetail },
    ],
  },
]);
