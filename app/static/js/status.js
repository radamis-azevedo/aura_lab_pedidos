/* app/static/js/status.js */

document.addEventListener("DOMContentLoaded", function() {
    
    const loader = document.getElementById("loader-overlay");
    const statusSelect = document.getElementById("status");
    const backBtn = document.querySelector(".btn-back");
    const CONFIG = window.StatusConfig || {};

    // --- FUNÇÕES DE INTERFACE ---

    window.showLoading = function(msg) {
        document.querySelector(".loader-text").textContent = msg || "Processando...";
        loader.style.display = "flex";
    };

    // NOVO: Função para abrir o Modal
    window.showModal = function(titulo, mensagem, icone = "⚠️") {
        const modal = document.getElementById("custom-modal");
        document.getElementById("modal-title").innerText = titulo;
        document.getElementById("modal-msg").innerText = mensagem;
        document.getElementById("modal-icon").innerText = icone;
        
        modal.style.display = "flex";
        // Pequeno delay para animação CSS
        setTimeout(() => modal.classList.add("active"), 10);
    };

    // NOVO: Função para fechar o Modal
    window.closeModal = function() {
        const modal = document.getElementById("custom-modal");
        modal.classList.remove("active");
        setTimeout(() => modal.style.display = "none", 300);
    };

    // --- VALIDAÇÃO E SUBMIT ---

    const formStatus = document.getElementById("status-form");
    if (formStatus) {
        formStatus.addEventListener("submit", (e) => {
            const dtInput = document.getElementById("dt_hr_status").value;
            const statusAtual = document.getElementById("status").value;
            const rowIndex = document.getElementById("row_index").value;

            // 1. Validação: Pedido Registrado Manual
            if (!rowIndex && statusAtual === "Pedido Registrado") {
                e.preventDefault();
                showModal("Ação Negada", "O status 'Pedido Registrado' é automático e não pode ser inserido manualmente.", "🚫");
                return;
            }

            // 2. Validação: Linha do Tempo
            if (CONFIG.dataLimite && dtInput) {
                if (dtInput < CONFIG.dataLimite) {
                    // Se for novo registro (!rowIndex), bloqueia
                    if (!rowIndex) { 
                        e.preventDefault();
                        
                        let dataFormatada = CONFIG.dataLimite;
                        try {
                            const [ano, mes, diaHora] = CONFIG.dataLimite.split("-");
                            const [dia, hora] = diaHora.split("T");
                            dataFormatada = `${dia}/${mes}/${ano} às ${hora}`;
                        } catch(err) {}

                        showModal(
                            "Data Inválida", 
                            `Você não pode incluir um status com data anterior ao registro inicial do pedido.\n\nData do Registro: ${dataFormatada}`,
                            "📅"
                        );
                        return;
                    }
                }
            }

            showLoading("Salvando Status...");
        });
    }

    // --- DELETE ---
    const formDelete = document.getElementById("delete-form");
    if (formDelete) {
        formDelete.addEventListener("submit", (e) => {
            if(!confirm("⚠️ Tem certeza que deseja excluir este histórico?")) {
                e.preventDefault();
            } else {
                showLoading("Excluindo...");
            }
        });
    }

    // --- PRAZO ---
    if (statusSelect) {
        statusSelect.addEventListener("change", function() {
            const statusSelecionado = this.value;
            const containerPrazo = document.getElementById("container-prazo");
            const inputPrazo = document.getElementById("prazo");
            const regra = CONFIG.statusPrazoObrig ? CONFIG.statusPrazoObrig[statusSelecionado] : "";
            
            if (regra === "S" || regra === "") {
                containerPrazo.style.display = "block";
                inputPrazo.required = (regra === "S");
            } else {
                inputPrazo.value = ""; 
                containerPrazo.style.display = "none"; 
                inputPrazo.required = false;
            }
        });
    }

    // --- VOLTAR ---
    if (backBtn) {
        backBtn.addEventListener("click", (e) => {
            e.preventDefault();
            const ultima = sessionStorage.getItem("ultima_rota");
            if (ultima && (ultima.includes("/detalhes") || ultima === "/")) {
                window.location.href = ultima;
            } else {
                window.location.href = "/";
            }
        });
    }

    window.resetarFormulario();
});

// --- FUNÇÕES GLOBAIS ---

window.editarHistorico = function(status, dt_hr_status, prazo, dt_hr_prazo, obs, row_index) {
    const CONFIG = window.StatusConfig || {};
    
    document.getElementById("form-title").innerHTML = '<i class="fas fa-edit"></i> Editar Status';
    document.getElementById("save-btn").innerHTML = '<i class="fas fa-sync-alt"></i> Atualizar';
    
    const statusSelect = document.getElementById("status");
    let optionExists = Array.from(statusSelect.options).some(opt => opt.value === status);
    
    if (!optionExists) {
        let opt = document.createElement("option");
        opt.value = status;
        opt.text = status;
        statusSelect.add(opt);
    }

    statusSelect.value = status;
    statusSelect.dispatchEvent(new Event('change'));
    
    document.getElementById("dt_hr_status").value = formatarInputDateTime(dt_hr_status);
    document.getElementById("prazo").value = prazo;
    document.getElementById("obs").value = obs;
    document.getElementById("row_index").value = row_index;
    
    const btnDel = document.getElementById("delete-btn");
    const formDel = document.getElementById("delete-form");
    
    // CORREÇÃO: Usar 'flex' para respeitar o CSS e não quebrar layout
    btnDel.style.display = "flex"; 
    formDel.action = `/status/${CONFIG.nrPed}/delete/${row_index}`;
    
    document.querySelector(".status-form-box").scrollIntoView({ behavior: 'smooth' });
};

window.resetarFormulario = function() {
    const CONFIG = window.StatusConfig || {};

    document.getElementById("form-title").innerHTML = '<i class="fas fa-plus-circle"></i> Incluir Novo Status';
    document.getElementById("save-btn").innerHTML = '<i class="fas fa-save"></i> Salvar';
    
    const statusSelect = document.getElementById("status");
    for (let i = 0; i < statusSelect.options.length; i++) {
        if (statusSelect.options[i].value === "Pedido Registrado") {
            statusSelect.remove(i);
        }
    }

    document.getElementById("status-form").reset();
    
    const dtEl = document.getElementById("dt_hr_status");
    if(dtEl && CONFIG.nowStr) dtEl.value = CONFIG.nowStr; 

    document.getElementById("row_index").value = "";
    document.getElementById("delete-btn").style.display = "none";
    document.getElementById("delete-form").action = "";
    
    const containerPrazo = document.getElementById("container-prazo");
    if(containerPrazo) containerPrazo.style.display = "none";
};

function formatarInputDateTime(str) {
    if (!str) return "";
    try {
        const [d, t] = str.split(" ");
        const [day, month, year] = d.split("/");
        return `${year}-${month}-${day}T${t.substring(0, 5)}`;
    } catch (e) { return ""; }
}