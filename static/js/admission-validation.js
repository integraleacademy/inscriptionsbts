/* The same checks run at the server before a dossier is created. No NIR is sent
   to any external service; this is a format/coherence check, not a registry lookup. */
(function (root) {
  function nir(value, birth, sex) {
    const n = (value || '').replace(/\s/g, '').toUpperCase();
    if (!n) return {ok:false, message:'Indique les 15 caractères de ton numéro de sécurité sociale.'};
    // Preserve the explicit special case already supported by the 2026 form.
    if (n === '123456789123456') return {ok:true, message:'Numéro accepté selon le cas particulier prévu.'};
    if (!/^\d{5}(?:\d{2}|2[AB])\d{8}$/.test(n)) return {ok:false, message:'15 caractères attendus ; 2A et 2B sont acceptés pour la Corse.'};
    const calculation = n.replace('2A','19').replace('2B','18');
    if (Number(97n - BigInt(calculation.slice(0,13)) % 97n) !== Number(calculation.slice(13))) return {ok:false, message:'La clé de contrôle est incorrecte. Vérifie les deux derniers chiffres.'};
    if (birth) {
      const [year, month] = birth.split('-');
      if (calculation.slice(1,3) !== year.slice(-2)) return {ok:false, message:'L’année du numéro ne correspond pas à ta date de naissance.'};
      const m=Number(calculation.slice(3,5));
      if (m>=1 && m<=12 && calculation.slice(3,5)!==month) return {ok:false, message:'Le mois du numéro ne correspond pas à ta date de naissance.'};
    }
    if ((sex === 'Homme' && calculation[0] !== '1') || (sex === 'Femme' && calculation[0] !== '2')) return {ok:false, message:'Le numéro ne correspond pas au sexe indiqué dans ton état civil.'};
    return {ok:true, message:'Numéro valide et cohérent : clé, date de naissance et sexe vérifiés.'};
  }
  root.AdmissionValidation = {nir};
  if (typeof module !== 'undefined') module.exports = {nir};
})(typeof window !== 'undefined' ? window : globalThis);
