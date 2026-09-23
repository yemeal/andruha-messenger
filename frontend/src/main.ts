import { createApp } from "vue";
import { createRouter, createWebHistory } from "vue-router";
import App from "./App.vue";
import Landing from "./pages/Landing.vue";
import Auth from "./pages/Auth.vue";
import Messenger from "./pages/Messenger.vue";
import "./styles.css";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", component: Landing },
    { path: "/login", component: Auth, props: { kind: "login" } },
    { path: "/register", component: Auth, props: { kind: "register" } },
    { path: "/app", component: Messenger, props: { demo: false } },
    { path: "/demo", component: Messenger, props: { demo: true } },
  ],
  scrollBehavior() {
    return { top: 0 };
  },
});

createApp(App).use(router).mount("#root");
