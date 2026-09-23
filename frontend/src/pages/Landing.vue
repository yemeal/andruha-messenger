<script setup lang="ts">
import { ref, onMounted, onUnmounted } from "vue";
import { RouterLink } from "vue-router";
import Lenis from "lenis";
import {
  ArrowDown,
  ArrowRight,
  ArrowUpRight,
  Fish,
  Heart,
  Menu,
} from "@lucide/vue";

const menuOpen = ref(false);
const playing = ref(false);
const caught = ref<string[]>([]);
const fish = ["one", "two", "three", "four", "five"];
let lenis: Lenis | null = null;
let frame = 0;
let observer: IntersectionObserver | null = null;

function catchFish(id: string) {
  if (!caught.value.includes(id)) caught.value = [...caught.value, id];
}
function tick(time: number) {
  lenis?.raf(time);
  frame = requestAnimationFrame(tick);
}

onMounted(() => {
  if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    lenis = new Lenis({
      duration: 1.18,
      smoothWheel: true,
      wheelMultiplier: 0.85,
    });
    frame = requestAnimationFrame(tick);
    observer = new IntersectionObserver(
      (entries) =>
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-visible");
            observer?.unobserve(entry.target);
          }
        }),
      { threshold: 0.16 },
    );
    document
      .querySelectorAll(".reveal")
      .forEach((node) => observer?.observe(node));
  }
});
onUnmounted(() => {
  cancelAnimationFrame(frame);
  lenis?.destroy();
  observer?.disconnect();
});
</script>

<template>
  <main class="landing">
    <section class="hero grain" aria-labelledby="hero-title">
      <header class="site-header">
        <RouterLink
          class="brand brand-light"
          to="/"
          aria-label="Андрюха — на главную"
          >андрюха<span class="brand-dot">.</span></RouterLink
        >
        <nav :class="['site-links', { open: menuOpen }]" aria-label="Навигация">
          <a href="#feeling" @click="menuOpen = false">Как это ощущается</a>
          <a href="#pond" @click="menuOpen = false">Поймать рыбку</a>
          <RouterLink to="/demo">Заглянуть внутрь</RouterLink>
        </nav>
        <div class="header-actions">
          <RouterLink class="header-login" to="/login"
            >Войти <ArrowUpRight :size="17" /></RouterLink
          ><button
            class="mobile-menu"
            aria-label="Открыть меню"
            :aria-expanded="menuOpen"
            @click="menuOpen = !menuOpen"
          >
            <Menu :size="24" />
          </button>
        </div>
      </header>
      <div class="hero-stage">
        <div class="hero-copy">
          <p class="eyebrow"><span class="eyebrow-square" /> Место для своих</p>
          <h1 id="hero-title">
            Есть люди,<br />с которыми<br /><span>просто.</span>
          </h1>
          <p class="hero-lede">
            И есть место, где можно быть собой.<br />Кажется, ты его нашёл.
          </p>
          <div class="hero-cta">
            <RouterLink class="primary-cta" to="/register"
              >Начать общаться <ArrowUpRight :size="21" /></RouterLink
            ><RouterLink class="text-cta" to="/demo"
              >Сначала осмотреться <ArrowRight :size="18"
            /></RouterLink>
          </div>
        </div>
        <div class="hero-art">
          <div class="orbit orbit-one" />
          <div class="orbit orbit-two" />
          <img
            src="/fox-hero.png"
            alt="Белоснежный мелованный лис сидит с хвостом позади туловища"
            class="hero-fox"
          />
          <div class="fox-note">Ну что, поболтаем? <span>↗</span></div>
        </div>
        <a class="scroll-cue" href="#feeling"
          >Листай вниз <ArrowDown :size="17" /></a
        ><span class="hero-index">01 / 03</span>
      </div>
    </section>
    <section
      id="feeling"
      class="feeling-section"
      aria-labelledby="feeling-title"
    >
      <div class="feeling-top reveal">
        <span class="section-number">/ 01</span>
        <p>Место, где переписка<br />чувствуется ближе</p>
      </div>
      <div class="feeling-main">
        <h2 id="feeling-title" class="reveal">
          Можно просто<br /><span>«привет».</span>
        </h2>
        <div class="feeling-aside reveal">
          <div class="little-sun">✳</div>
          <p>
            Без повода. Без правильных слов. Просто напиши тому, кто поймёт.
          </p>
        </div>
      </div>
      <div class="floating-messages" aria-hidden="true">
        <span class="floating-bubble bubble-one">Ты как там?</span
        ><span class="floating-bubble bubble-two">Уже лучше ☺</span
        ><span class="floating-bubble bubble-three">Вот и хорошо.</span>
      </div>
    </section>
    <section id="pond" class="pond-section" aria-labelledby="pond-title">
      <div class="pond-heading reveal">
        <p class="eyebrow dark-eyebrow">
          <span class="eyebrow-square" /> Небольшая пауза
        </p>
        <h2 id="pond-title">Поймай момент.<br /><em>И пару рыбок.</em></h2>
        <p>
          Здесь никуда не нужно спешить. Даже если это просто маленькая игра.
        </p>
        <button v-if="!playing" class="pill-button" @click="playing = true">
          Давай попробуем <ArrowUpRight :size="18" />
        </button>
        <div v-else class="game-score" role="status">
          Поймано: {{ caught.length }} / {{ fish.length }}
        </div>
      </div>
      <div
        :class="['pond', { 'pond-playing': playing }]"
        aria-label="Мини-игра: поймай пять рыбок"
      >
        <div class="pond-ripple pond-ripple-a" />
        <div class="pond-ripple pond-ripple-b" />
        <span class="pond-star star-a">✳</span
        ><span class="pond-star star-b">✳</span
        ><button
          v-for="(item, index) in fish"
          :key="item"
          :class="[
            'game-fish',
            `fish-${item}`,
            { 'fish-caught': caught.includes(item) },
          ]"
          :disabled="!playing || caught.includes(item)"
          :aria-label="`Поймать рыбку ${index + 1}`"
          @click="catchFish(item)"
        >
          <Fish :size="index % 2 ? 64 : 88" :stroke-width="1.25" />
        </button>
        <div
          v-if="caught.length === fish.length"
          class="game-win"
          role="status"
        >
          <Heart :size="22" fill="currentColor" /> Улов принят. Сегодня ты
          молодец.
        </div>
        <span class="pond-caption">{{
          playing ? "Нажимай на рыбок" : "Тут кто-то плавает…"
        }}</span>
      </div>
      <img
        src="/fox-right.png"
        alt="Белоснежный лис бежит вправо"
        class="pond-fox"
      />
    </section>
    <section class="closing-section grain">
      <div class="closing-inner">
        <div>
          <p class="eyebrow"><span class="eyebrow-square" /> Увидимся там</p>
          <h2>Свои люди.<br />На связи.</h2>
          <RouterLink class="closing-button" to="/register"
            >Заходи <ArrowUpRight :size="21"
          /></RouterLink>
        </div>
        <img src="/fox-front.png" alt="Белоснежный лис смотрит прямо на вас" />
      </div>
    </section>
    <footer class="landing-footer">
      <RouterLink class="brand" to="/"
        >андрюха<span class="brand-dot">.</span></RouterLink
      ><span>Ближе, даже издалека.</span
      ><span>© {{ new Date().getFullYear() }} Андрюха</span>
    </footer>
  </main>
</template>
