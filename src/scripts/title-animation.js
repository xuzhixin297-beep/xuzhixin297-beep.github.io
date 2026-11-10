const title = document.querySelector(".logo.animated-title");
  const trigger = title?.querySelector(".letter-trigger");
  const forwardFormula = title?.querySelector(".formula-forward");
  const reverseFormula = title?.querySelector(".formula-reverse");

  if (
    title instanceof HTMLElement &&
    trigger instanceof HTMLButtonElement &&
    forwardFormula instanceof HTMLElement &&
    reverseFormula instanceof HTMLElement
  ) {
    let isAnti = false;
    let isAnimating = false;
    let changeTimer;
    let finishTimer;

    // Restore the saved theme
    const savedTheme = localStorage.getItem("theme");

    trigger.addEventListener("click", () => {
      if (isAnimating) return;
      isAnimating = true;

      const rect = title.getBoundingClientRect();

      // Create a temporary copy of the navigation title.
      const clone = title.cloneNode(true);
      if (!(clone instanceof HTMLElement)) {
        isAnimating = false;
        return;
      }

      clone.classList.add("cinematic-clone");
      clone.setAttribute("aria-hidden", "true");

      // Set the equation appropriate to the direction.
      const cloneForward = clone.querySelector(".formula-forward");
      const cloneReverse = clone.querySelector(".formula-reverse");

      if (
        !(cloneForward instanceof HTMLElement) ||
        !(cloneReverse instanceof HTMLElement)
      ) {
        isAnimating = false;
        return;
      }

      cloneForward.style.display = isAnti ? "none" : "flex";
      cloneReverse.style.display = isAnti ? "inline" : "none";

      // Place the copy exactly over the original title.
      clone.style.left = `${rect.left}px`;
      clone.style.top = `${rect.top}px`;
      clone.style.transform = "translate(0, 0) scale(1)";
      clone.style.transition = "none";

      const backdrop = document.createElement("div");
      backdrop.className = "cinematic-backdrop";
      document.body.append(backdrop);
      document.body.append(clone);
	  document.body.classList.add("cinematic-active");

      // Keep the original layout intact, but hide its text temporarily.
      title.style.visibility = "hidden";

      // Allow the browser to register the starting position.
      void clone.offsetWidth;

      clone.style.transition = "";
      backdrop.classList.add("is-visible");

      // Move the title to the center and magnify it.
      const scale = Math.min(
        2.2,
        (window.innerWidth - 40) / rect.width
      );
      const dx = window.innerWidth / 2 - (rect.left + rect.width / 2);
      const dy = window.innerHeight / 2 - (rect.top + rect.height / 2);

      clone.style.transform =
        `translate(${dx}px, ${dy}px) scale(${scale})`;

      // Show the formula after the title reaches the center.
      window.setTimeout(() => {
        clone.classList.add("formula-active");
      }, 700);

      // Change the letter after the equation has appeared.
      changeTimer = window.setTimeout(() => {
        isAnti = !isAnti;

        clone.classList.toggle("is-anti", isAnti);

        trigger.setAttribute("aria-pressed", String(isAnti));
        title.setAttribute(
          "aria-label",
          isAnti ? "Antimundane sprǣc" : "Antemundane sprǣc"
        );
      }, 1500);

      // Fade out the cinematic scene and restore the page.
      finishTimer = window.setTimeout(() => {
        title.classList.toggle("is-anti", isAnti);
       title.style.visibility = "";
       clone.remove();
       backdrop.remove();
       document.body.classList.remove("cinematic-active");

     isAnimating = false;
      }, 3100);
    });
};

// Theme switching
const themeButton = document.querySelector("#theme-toggle");

// Check the current theme
const isLightTheme = document.documentElement.classList.contains("light-theme");

//Update button text if the button exists
if (themeButton) {
    themeButton.textContent = isLightTheme ? "Dark mode" : "Light mode";
    
    themeButton.addEventListener("click", ()=>{
      document.documentElement.classList.toggle("light-theme");
    
    
      const newIsLightTheme = document.documentElement.classList.contains("light-theme");
    
      localStorage.setItem("theme", newIsLightTheme ? "light" : "dark");

      themeButton.textContent = newIsLightTheme ? "Dark mode" : "Light mode";
    });
}